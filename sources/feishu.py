"""Feishu (Lark) document service — create documents via Open API and push links via webhook."""

import json
import logging
import time

import requests

logger = logging.getLogger("sources.feishu")

API_BASE = "https://open.feishu.cn/open-apis"

# Cache tenant_access_token (valid for ~2 hours, we refresh at 1.5h)
_token_cache: dict = {}  # {key: (token, expire_ts)}
TOKEN_TTL = 5400  # 1.5 hours in seconds


class FeishuDocService:
    """Create Feishu documents and push links via webhook."""

    def _get_tenant_access_token(self, app_id: str, app_secret: str) -> str:
        """Obtain a tenant_access_token from Feishu, with caching.

        Uses the internal app token endpoint (no user login required).
        Token is cached for 1.5 hours (official TTL is 2 hours).
        """
        cache_key = f"{app_id}"
        cached = _token_cache.get(cache_key)
        if cached and cached[1] > time.time():
            return cached[0]

        url = f"{API_BASE}/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={
            "app_id": app_id,
            "app_secret": app_secret,
        }, timeout=10)
        data = resp.json()

        if data.get("code") != 0:
            msg = data.get("msg", str(data))
            raise RuntimeError(f"获取 tenant_access_token 失败: {msg}")

        token = data["tenant_access_token"]
        _token_cache[cache_key] = (token, time.time() + TOKEN_TTL)
        logger.info("Obtained tenant_access_token for app_id=%s (expires in %ds)", app_id, TOKEN_TTL)
        return token

    def _auth_headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def create_document(self, token: str, title: str, folder_token: str = "") -> dict:
        """Create an empty Feishu docx document."""
        url = f"{API_BASE}/docx/v1/documents"
        body = {"title": title}
        if folder_token:
            body["folder_token"] = folder_token

        resp = requests.post(url, json=body, headers=self._auth_headers(token), timeout=15)
        data = resp.json()

        if data.get("code") != 0:
            msg = data.get("msg", str(data))
            raise RuntimeError(f"创建文档失败: {msg}")

        doc = data.get("data", {}).get("document", {})
        logger.info("Created document: id=%s, title=%s", doc.get("document_id"), doc.get("title"))
        return doc

    def _list_folder(self, token: str, folder_token: str) -> list:
        """List files/folders inside a folder."""
        url = f"{API_BASE}/drive/v1/files"
        params = {"folder_token": folder_token, "page_size": 200}
        try:
            resp = requests.get(url, params=params, headers=self._auth_headers(token), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("files", [])
        except Exception as e:
            logger.warning("Failed to list folder %s: %s", folder_token, e)
        return []

    def _find_or_create_subfolder(self, token: str, parent_token: str, folder_name: str) -> str:
        """Find a subfolder by name, or create it if it doesn't exist. Returns folder token."""
        # Search existing children
        files = self._list_folder(token, parent_token)
        for f in files:
            if f.get("type") == "folder" and f.get("name") == folder_name:
                logger.info("Found existing folder '%s': token=%s", folder_name, f.get("token"))
                return f["token"]

        # Create new folder
        url = f"{API_BASE}/drive/v1/files/create_folder"
        body = {"name": folder_name, "folder_token": parent_token}
        resp = requests.post(url, json=body, headers=self._auth_headers(token), timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            msg = data.get("msg", str(data))
            raise RuntimeError(f"创建文件夹 '{folder_name}' 失败: {msg}")
        new_token = data.get("data", {}).get("token", "")
        logger.info("Created folder '%s': token=%s", folder_name, new_token)
        return new_token

    def ensure_folder_path(self, token: str, base_folder_token: str, path_parts: list) -> str:
        """Ensure a nested folder path exists, creating folders as needed.

        Args:
            token: tenant_access_token
            base_folder_token: The root folder token to start from
            path_parts: List of folder names, e.g. ["github", "apache-iceberg"]

        Returns:
            The folder token of the deepest folder.
        """
        current_token = base_folder_token
        for part in path_parts:
            if not part:
                continue
            current_token = self._find_or_create_subfolder(token, current_token, part)
        return current_token

    def _delete_file(self, token: str, file_token: str, file_type: str = "docx") -> bool:
        """Delete a file from Drive. Returns True on success."""
        url = f"{API_BASE}/drive/v1/files/{file_token}?type={file_type}"
        try:
            resp = requests.delete(url, headers=self._auth_headers(token), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                logger.info("Deleted file: token=%s", file_token)
                return True
            else:
                logger.warning("Failed to delete file %s: %s", file_token, data.get("msg", ""))
        except Exception as e:
            logger.warning("Failed to delete file %s: %s", file_token, e)
        return False

    def delete_existing_doc(self, token: str, folder_token: str, title: str) -> int:
        """Find and delete documents with matching title in a folder. Returns count deleted."""
        files = self._list_folder(token, folder_token)
        deleted = 0
        for f in files:
            if f.get("type") == "docx" and f.get("name") == title:
                if self._delete_file(token, f["token"], "docx"):
                    deleted += 1
        return deleted

    def _markdown_to_blocks(self, md_text: str) -> list:
        """Convert Markdown text to Feishu document block structures.

        Handles headings, paragraphs, bold, links, code blocks, lists,
        and horizontal rules using Feishu's block types.
        """
        import re
        from urllib.parse import quote

        lines = md_text.strip().split("\n")
        blocks = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # Code block (fenced)
            if line.strip().startswith("```"):
                code_lines = []
                lang = line.strip()[3:].strip()
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                i += 1  # skip closing ```
                code_content = "\n".join(code_lines) or " "
                blocks.append({
                    "block_type": 14,  # code block
                    "code": {
                        "elements": [{
                            "text_run": {
                                "content": code_content,
                            }
                        }],
                        "language": self._map_code_language(lang),
                    },
                })
                continue

            # Horizontal rule
            if re.match(r'^---+\s*$', line) or re.match(r'^\*\*\*+\s*$', line):
                blocks.append({"block_type": 22, "divider": {}})
                i += 1
                continue

            # Headings
            heading_match = re.match(r'^(#{1,9})\s+(.+)$', line)
            if heading_match:
                level = min(len(heading_match.group(1)), 9)
                text = heading_match.group(2).strip()
                # Feishu heading block_type: heading1=3, heading2=4, ..., heading9=11
                block_type = 2 + level
                heading_key = f"heading{level}"
                blocks.append({
                    "block_type": block_type,
                    heading_key: {
                        "elements": self._parse_inline_elements(text),
                    },
                })
                i += 1
                continue

            # Unordered list
            ul_match = re.match(r'^[\-\*]\s+(.+)$', line)
            if ul_match:
                blocks.append({
                    "block_type": 12,  # bullet
                    "bullet": {
                        "elements": self._parse_inline_elements(ul_match.group(1)),
                    },
                })
                i += 1
                continue

            # Ordered list
            ol_match = re.match(r'^\d+\.\s+(.+)$', line)
            if ol_match:
                blocks.append({
                    "block_type": 13,  # ordered
                    "ordered": {
                        "elements": self._parse_inline_elements(ol_match.group(1)),
                    },
                })
                i += 1
                continue

            # Empty line — skip
            if line.strip() == "":
                i += 1
                continue

            # Regular paragraph
            blocks.append({
                "block_type": 2,  # text (paragraph)
                "text": {
                    "elements": self._parse_inline_elements(line),
                },
            })
            i += 1

        return blocks

    def _parse_inline_elements(self, text: str) -> list:
        """Parse inline markdown (bold, links, code) into Feishu text elements."""
        import re
        from urllib.parse import quote

        elements = []
        # Pattern: match **bold**, [link](url), `code`, or plain text
        pattern = r'(\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\)|`([^`]+)`)'
        last_end = 0

        for m in re.finditer(pattern, text):
            # Add plain text before this match
            if m.start() > last_end:
                plain = text[last_end:m.start()]
                if plain:
                    elements.append({
                        "text_run": {
                            "content": plain,
                        }
                    })

            if m.group(2):  # **bold**
                elements.append({
                    "text_run": {
                        "content": m.group(2),
                        "text_element_style": {"bold": True},
                    }
                })
            elif m.group(3):  # [text](url)
                raw_url = m.group(4).strip()
                # Feishu requires percent-encoded URLs
                if raw_url.startswith("http"):
                    encoded_url = quote(raw_url, safe='')
                else:
                    encoded_url = raw_url
                elements.append({
                    "text_run": {
                        "content": m.group(3),
                        "text_element_style": {
                            "link": {"url": encoded_url},
                        },
                    }
                })
            elif m.group(5):  # `code`
                elements.append({
                    "text_run": {
                        "content": m.group(5),
                        "text_element_style": {"inline_code": True},
                    }
                })

            last_end = m.end()

        # Remaining plain text
        if last_end < len(text):
            remaining = text[last_end:]
            if remaining:
                elements.append({
                    "text_run": {
                        "content": remaining,
                    }
                })

        # If no elements were found, treat entire text as plain
        if not elements:
            elements.append({
                "text_run": {
                    "content": text,
                }
            })

        return elements

    def _map_code_language(self, lang: str) -> int:
        """Map language identifier to Feishu code block language enum."""
        lang_map = {
            "python": 49, "java": 28, "javascript": 29, "js": 29,
            "typescript": 64, "ts": 64, "go": 21, "rust": 54,
            "c": 6, "cpp": 7, "c++": 7, "sql": 58, "shell": 56,
            "bash": 3, "json": 30, "yaml": 71, "xml": 69,
            "html": 24, "css": 10, "markdown": 37, "md": 37,
        }
        return lang_map.get(lang.lower(), 47)  # 47 = PlainText

    def _make_plain_text_block(self, text: str) -> dict:
        """Create a simple plain text paragraph block (always safe)."""
        return {
            "block_type": 2,
            "text": {
                "elements": [{"text_run": {"content": text, "text_element_style": {}}}]
            },
        }

    def _insert_single_block(self, token: str, document_id: str, block: dict, index: int) -> bool:
        """Try to insert a single block. Returns True on success."""
        url = f"{API_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children"
        body = {"children": [block], "index": index}
        try:
            resp = requests.post(url, json=body, headers=self._auth_headers(token), timeout=30)
            data = resp.json()
            if data.get("code") == 0:
                return True
            logger.warning("Single block insert failed: code=%s msg=%s block_type=%s",
                           data.get("code"), data.get("msg"), block.get("block_type"))
            return False
        except Exception as e:
            logger.warning("Single block insert error: %s", e)
            return False

    def insert_blocks(self, token: str, document_id: str, blocks: list) -> None:
        """Insert content blocks into a document with automatic fallback.

        Strategy:
        1. Try to insert all blocks in a single batch.
        2. If batch fails, fall back to inserting blocks one-by-one.
        3. For any single block that fails, degrade it to plain text.
        """
        if not blocks:
            return

        url = f"{API_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children"

        # Try batch insert first (fast path)
        body = {"children": blocks, "index": 0}
        try:
            resp = requests.post(url, json=body, headers=self._auth_headers(token), timeout=60)
            data = resp.json()
            if data.get("code") == 0:
                logger.info("Batch inserted %d blocks into document %s", len(blocks), document_id)
                return
            logger.warning("Batch insert failed (code=%s msg=%s), falling back to one-by-one",
                           data.get("code"), data.get("msg"))
        except Exception as e:
            logger.warning("Batch insert error: %s, falling back to one-by-one", e)

        # Fallback: insert blocks one-by-one
        inserted = 0
        for i, block in enumerate(blocks):
            # Try original block
            if self._insert_single_block(token, document_id, block, inserted):
                inserted += 1
                continue

            # If it failed, extract text content and insert as plain text
            text_content = self._extract_text_from_block(block)
            if text_content:
                fallback = self._make_plain_text_block(text_content)
                if self._insert_single_block(token, document_id, fallback, inserted):
                    inserted += 1
                    logger.info("Block %d: used plain-text fallback for block_type=%s", i, block.get("block_type"))
                else:
                    logger.warning("Block %d: even plain-text fallback failed, skipping", i)
            else:
                logger.warning("Block %d: no text to extract, skipping block_type=%s", i, block.get("block_type"))

        logger.info("Inserted %d/%d blocks into document %s", inserted, len(blocks), document_id)

    def _extract_text_from_block(self, block: dict) -> str:
        """Extract plain text from any block structure."""
        # Check all possible content fields
        for key in ("text", "heading1", "heading2", "heading3", "heading4",
                     "heading5", "heading6", "heading7", "heading8", "heading9",
                     "bullet", "ordered", "code"):
            content = block.get(key)
            if content and isinstance(content, dict):
                elements = content.get("elements", [])
                parts = []
                for el in elements:
                    tr = el.get("text_run", {})
                    if tr.get("content"):
                        parts.append(tr["content"])
                if parts:
                    return "".join(parts)
        # Divider → use a text separator
        if block.get("block_type") == 22:
            return "————————"
        return ""

    def create_doc_from_markdown(
        self, app_id: str, app_secret: str, title: str,
        md_text: str, folder_token: str = "", owner_email: str = "",
        sub_folder: str = "",
    ) -> dict:
        """One-stop method: create a Feishu document from Markdown.

        1. Obtain tenant_access_token
        2. Ensure sub-folder path exists (if sub_folder provided)
        3. Create empty document
        4. Convert Markdown to blocks
        5. Insert blocks into the document
        6. Grant full_access to owner (if owner_email provided)

        Returns:
            dict with keys: document_id, doc_url, title
        """
        token = self._get_tenant_access_token(app_id, app_secret)

        # Resolve target folder: create sub-folder path if needed
        target_folder = folder_token
        if sub_folder and folder_token:
            path_parts = [p.strip() for p in sub_folder.replace("\\", "/").split("/") if p.strip()]
            if path_parts:
                target_folder = self.ensure_folder_path(token, folder_token, path_parts)
                logger.info("Resolved sub-folder '%s' -> token=%s", sub_folder, target_folder)

        doc = self.create_document(token, title, target_folder)
        document_id = doc["document_id"]

        blocks = self._markdown_to_blocks(md_text)
        if blocks:
            self.insert_blocks(token, document_id, blocks)

        # Grant full_access to the owner
        if owner_email:
            self._grant_permission(token, document_id, owner_email)

        # Set document to "anyone on the internet with the link can read"
        self._set_public_readable(token, document_id)

        # Get the real browser-accessible URL via Drive metas API
        doc_url = self._get_doc_url(token, document_id)
        logger.info("Created document from Markdown: url=%s", doc_url)
        return {
            "document_id": document_id,
            "doc_url": doc_url,
            "title": title,
        }

    def _grant_permission(self, token: str, document_id: str, contact: str) -> None:
        """Grant full_access permission on a document to a user by email or phone."""
        # Auto-detect: email contains '@', otherwise treat as phone
        if "@" in contact:
            member_type = "email"
            member_id = contact
        else:
            member_type = "phone"
            # Ensure country code prefix (default +86 for China)
            member_id = contact if contact.startswith("+") else f"+86{contact}"

        url = f"{API_BASE}/drive/v1/permissions/{document_id}/members?type=docx"
        body = {
            "member_type": member_type,
            "member_id": member_id,
            "perm": "full_access",
        }
        try:
            resp = requests.post(url, json=body, headers=self._auth_headers(token), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                logger.info("Granted full_access to %s on document %s", contact, document_id)
            else:
                logger.warning("Failed to grant permission to %s: %s",
                               contact, data.get("msg", str(data)))
        except Exception as e:
            logger.warning("Failed to grant permission to %s: %s", contact, e)

    def _set_public_readable(self, token: str, document_id: str) -> None:
        """Set document to 'anyone on the internet with the link can read'."""
        url = f"{API_BASE}/drive/v1/permissions/{document_id}/public?type=docx"
        body = {"external_access_entity": "open", "link_share_entity": "anyone_readable"}
        try:
            resp = requests.patch(url, json=body, headers=self._auth_headers(token), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                logger.info("Set document %s to public readable", document_id)
            else:
                logger.warning("Failed to set public readable: %s", data.get("msg", ""))
        except Exception as e:
            logger.warning("Failed to set public readable: %s", e)

    def _get_doc_url(self, token: str, document_id: str) -> str:
        """Get the browser-accessible URL for a document via Drive metas API."""
        try:
            url = f"{API_BASE}/drive/v1/metas/batch_query"
            body = {
                "request_docs": [{"doc_token": document_id, "doc_type": "docx"}],
                "with_url": True,
            }
            resp = requests.post(url, json=body, headers=self._auth_headers(token), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                metas = data.get("data", {}).get("metas", [])
                if metas and metas[0].get("url"):
                    return metas[0]["url"]
        except Exception as e:
            logger.warning("Failed to get doc URL from metas API: %s", e)
        # Fallback: construct a generic URL (user may need to adjust domain)
        return f"https://feishu.cn/docx/{document_id}"

    @staticmethod
    def push_link_to_webhook(webhook_url: str, title: str, doc_url: str) -> dict:
        """Push a document link to a Feishu group via custom bot webhook.

        Sends a rich-text message with the document title and a clickable link.

        Returns:
            dict with the webhook response
        """
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": f"📄 {title}",
                        "content": [
                            [
                                {"tag": "text", "text": "新的 GitHub 摘要文档已生成：\n"},
                            ],
                            [
                                {"tag": "a", "text": f"👉 点击查看：{title}", "href": doc_url},
                            ],
                        ],
                    }
                }
            },
        }

        resp = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        result = resp.json()

        if result.get("code") == 0 or result.get("StatusCode") == 0:
            logger.info("Pushed doc link to webhook: url=%s", doc_url)
        else:
            msg = result.get("msg") or result.get("StatusMessage") or str(result)
            logger.warning("Webhook push returned error: %s", msg)

        return result
