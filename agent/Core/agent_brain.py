"""
Agent Brain
Core logic for the Osmo AI Agent.
Handles model routing, prompt preparation, and execution.
"""

from typing import List, Dict, Any, Optional
import re
from agent.Core.llm_factory import LLMFactory

class AgentBrain:
    """The central intelligence unit for Osmo."""
    
    def __init__(
        self,
        model_id: str = "anthropic/claude-3.5-sonnet",
        reasoning_effort: Optional[str] = None,
        tool_states: Optional[Dict[str, Any]] = None
    ):
        self.model_id = model_id
        self.llm = LLMFactory.get_llm(model_id, reasoning_effort=reasoning_effort)
        self.system_prompt = LLMFactory.get_system_prompt(
            model_id,
            reasoning_effort=reasoning_effort,
            tool_states=tool_states
        )

    def _supports_multimodal(self) -> bool:
        model = (self.model_id or "").lower()
        if model.startswith("groq/"):
            return False
        multimodal_keywords = (
            "gpt-4o", "gpt-4.1", "gpt-4v", "vision",
            "claude", "gemini", "llava", "qwen-vl", "pixtral",
            "grok-vision", "grok-2-vision"
        )
        return any(k in model for k in multimodal_keywords)
        
    async def chat(self, user_message: str, history: List[Dict[str, str]] = None, attachments: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Processes a user message and returns the response with metadata.
        """
        def build_user_content(message: str, files: Optional[List[Dict[str, Any]]], allow_multimodal: bool):
            if not files:
                return message

            MAX_INLINE_CHARS = 8000

            def attachments_as_text() -> str:
                lines = []
                for f in files:
                    name = f.get("name") or "attachment"
                    mime = f.get("type") or "application/octet-stream"
                    data = f.get("data") or f.get("data_url") or ""
                    line = f"- {name} ({mime})"
                    if data:
                        line += f"\n  base64 (truncated): {data[:MAX_INLINE_CHARS]}"
                    lines.append(line)
                header = "Attachments:\n" + "\n".join(lines)
                return f"{message}\n\n{header}" if message else header

            has_image = any((f.get("type") or "").startswith("image/") and (f.get("data") or f.get("data_url")) for f in files)
            if not allow_multimodal or not has_image:
                return attachments_as_text()

            parts: List[Dict[str, Any]] = []
            if message:
                parts.append({"type": "text", "text": message})
            else:
                parts.append({"type": "text", "text": "User attached files."})

            for f in files:
                name = f.get("name") or "attachment"
                mime = f.get("type") or "application/octet-stream"
                data = f.get("data") or f.get("data_url") or ""

                if mime.startswith("image/") and data:
                    parts.append({"type": "image_url", "image_url": {"url": data}})
                else:
                    label = f"[Attachment: {name} ({mime})]"
                    if data:
                        label += f"\nData (base64, truncated): {data[:MAX_INLINE_CHARS]}"
                    parts.append({"type": "text", "text": label})

            return parts
        def extract_tag_block(text: str, tag: str) -> tuple[Optional[str], str]:
            pattern = re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.IGNORECASE | re.DOTALL)
            match = pattern.search(text)
            if not match:
                return None, text
            inner = match.group(1).strip()
            cleaned = (text[:match.start()] + text[match.end():]).strip()
            return inner, cleaned

        def strip_tags(text: str) -> str:
            tags = [
                "<final>", "</final>",
                "<reasoning_summary>", "</reasoning_summary>",
                "<summary>", "</summary>"
            ]
            for t in tags:
                text = text.replace(t, "")
            return text.strip()

        def parse_reasoning_lines(text: Optional[str]) -> List[str]:
            if not text:
                return []
            lines = []
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                line = re.sub(r"^[-*]\s+", "", line)
                lines.append(line)
            return lines

        # Prepare messages
        messages = [{"role": "system", "content": self.system_prompt}]
        
        if history:
            messages.extend(history)
            
        messages.append({"role": "user", "content": user_message})
        
        # Call LLM
        response = await self.llm.ainvoke(messages)
        
        # Extract metadata if available (handle multiple formats for compatibility)
        usage = {}
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            usage = response.usage_metadata
        elif hasattr(response, 'response_metadata'):
            usage = response.response_metadata.get('token_usage', {}) or response.response_metadata.get('usage', {})

        raw_content = response.content or ""
        final_block, after_final = extract_tag_block(raw_content, "final")
        reasoning_block, after_reasoning = extract_tag_block(after_final, "reasoning_summary")
        if not reasoning_block:
            reasoning_block, after_reasoning = extract_tag_block(after_reasoning, "summary")

        # Fallback: some providers may include reasoning in metadata
        if not reasoning_block and hasattr(response, "additional_kwargs"):
            reasoning_block = response.additional_kwargs.get("reasoning") or response.additional_kwargs.get("reasoning_content")

        content = final_block if final_block is not None else (after_reasoning or raw_content)
        content = strip_tags(content)
        thoughts = parse_reasoning_lines(reasoning_block)

        return {
            "content": content,
            "usage": usage,
            "thoughts": thoughts
        }

    async def stream(self, user_message: str, history: List[Dict[str, str]] = None, attachments: Optional[List[Dict[str, Any]]] = None):
        """
        Streams the model response. Yields dict events:
          - {"type": "delta", "content": "..."}
          - {"type": "thoughts", "thoughts": [ ... ]}
          - {"type": "done", "content": "...", "usage": {...}, "thoughts": [...]}
        """
        def build_user_content(message: str, files: Optional[List[Dict[str, Any]]], allow_multimodal: bool):
            if not files:
                return message

            MAX_INLINE_CHARS = 8000

            def attachments_as_text() -> str:
                lines = []
                for f in files:
                    name = f.get("name") or "attachment"
                    mime = f.get("type") or "application/octet-stream"
                    data = f.get("data") or f.get("data_url") or ""
                    line = f"- {name} ({mime})"
                    if data:
                        line += f"\n  base64 (truncated): {data[:MAX_INLINE_CHARS]}"
                    lines.append(line)
                header = "Attachments:\n" + "\n".join(lines)
                return f"{message}\n\n{header}" if message else header

            has_image = any((f.get("type") or "").startswith("image/") and (f.get("data") or f.get("data_url")) for f in files)
            if not allow_multimodal or not has_image:
                return attachments_as_text()

            parts: List[Dict[str, Any]] = []
            if message:
                parts.append({"type": "text", "text": message})
            else:
                parts.append({"type": "text", "text": "User attached files."})

            for f in files:
                name = f.get("name") or "attachment"
                mime = f.get("type") or "application/octet-stream"
                data = f.get("data") or f.get("data_url") or ""

                if mime.startswith("image/") and data:
                    parts.append({"type": "image_url", "image_url": {"url": data}})
                else:
                    label = f"[Attachment: {name} ({mime})]"
                    if data:
                        label += f"\nData (base64, truncated): {data[:MAX_INLINE_CHARS]}"
                    parts.append({"type": "text", "text": label})

            return parts
        def extract_tag_block(text: str, tag: str) -> tuple[Optional[str], str]:
            pattern = re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.IGNORECASE | re.DOTALL)
            match = pattern.search(text)
            if not match:
                return None, text
            inner = match.group(1).strip()
            cleaned = (text[:match.start()] + text[match.end():]).strip()
            return inner, cleaned

        def parse_reasoning_lines(text: Optional[str]) -> List[str]:
            if not text:
                return []
            lines = []
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                line = re.sub(r"^[-*]\s+", "", line)
                lines.append(line)
            return lines

        messages = [{"role": "system", "content": self.system_prompt}]
        if history:
            messages.extend(history)
        user_content = build_user_content(user_message, attachments, self._supports_multimodal())
        messages.append({"role": "user", "content": user_content})

        TAGS = [
            "<final>", "</final>",
            "<reasoning_summary>", "</reasoning_summary>",
            "<summary>", "</summary>"
        ]
        TAG_SET = {t.lower() for t in TAGS}

        tag_buffer = ""
        in_tag = False
        inside_reasoning = False
        content_buffer = ""
        full_text = ""
        reasoning_meta = ""
        thoughts: List[str] = []
        last_usage = {}
        reason_line_buffer = ""

        async for chunk in self.llm.astream(messages):
            if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                last_usage = chunk.usage_metadata
            elif hasattr(chunk, 'response_metadata'):
                last_usage = chunk.response_metadata.get('token_usage', {}) or chunk.response_metadata.get('usage', {}) or last_usage

            # capture reasoning metadata if provided
            if hasattr(chunk, "additional_kwargs") and chunk.additional_kwargs:
                reasoning_meta += chunk.additional_kwargs.get("reasoning") or chunk.additional_kwargs.get("reasoning_content") or ""

            piece = getattr(chunk, "content", None) or ""
            if not piece:
                continue

            full_text += piece

            for ch in piece:
                if in_tag:
                    tag_buffer += ch
                    buf_lower = tag_buffer.lower()
                    is_prefix = any(t.startswith(buf_lower) for t in TAG_SET)

                    if ch == ">" and buf_lower in TAG_SET:
                        # handle recognized tag
                        if buf_lower in ("<reasoning_summary>", "<summary>"):
                            inside_reasoning = True
                            reason_line_buffer = ""
                        elif buf_lower in ("</reasoning_summary>", "</summary>"):
                            inside_reasoning = False
                            if reason_line_buffer.strip():
                                line = reason_line_buffer.strip()
                                line = re.sub(r"^[-*]\s+", "", line)
                                if line:
                                    thoughts.append(line)
                                    yield {"type": "thoughts_delta", "thought": line}
                            reason_line_buffer = ""
                        # ignore <final> tags
                        tag_buffer = ""
                        in_tag = False
                        continue

                    if is_prefix:
                        continue

                    # Not a valid tag prefix, flush buffer as text
                    tail = tag_buffer[-1]
                    flush_text = tag_buffer[:-1]
                    if flush_text:
                        if inside_reasoning:
                            reason_line_buffer += flush_text
                            while "\n" in reason_line_buffer:
                                line, reason_line_buffer = reason_line_buffer.split("\n", 1)
                                line = line.strip()
                                if line:
                                    line = re.sub(r"^[-*]\s+", "", line)
                                    if line:
                                        thoughts.append(line)
                                        yield {"type": "thoughts_delta", "thought": line}
                        else:
                            content_buffer += flush_text
                            yield {"type": "delta", "content": flush_text}
                    tag_buffer = ""
                    in_tag = False
                    if tail == "<":
                        in_tag = True
                        tag_buffer = "<"
                    else:
                        if inside_reasoning:
                            reason_line_buffer += tail
                        else:
                            content_buffer += tail
                            yield {"type": "delta", "content": tail}
                    continue

                if ch == "<":
                    in_tag = True
                    tag_buffer = "<"
                    continue

                if inside_reasoning:
                    reason_line_buffer += ch
                    while "\n" in reason_line_buffer:
                        line, reason_line_buffer = reason_line_buffer.split("\n", 1)
                        line = line.strip()
                        if line:
                            line = re.sub(r"^[-*]\s+", "", line)
                            if line:
                                thoughts.append(line)
                                yield {"type": "thoughts_delta", "thought": line}
                else:
                    content_buffer += ch
                    yield {"type": "delta", "content": ch}

        # Flush any pending tag buffer as text
        if in_tag and tag_buffer:
            if inside_reasoning:
                reason_line_buffer += tag_buffer
            else:
                content_buffer += tag_buffer
                yield {"type": "delta", "content": tag_buffer}
            tag_buffer = ""
            in_tag = False

        if inside_reasoning and reason_line_buffer.strip():
            line = reason_line_buffer.strip()
            line = re.sub(r"^[-*]\s+", "", line)
            if line:
                thoughts.append(line)
                yield {"type": "thoughts_delta", "thought": line}

        # Extract reasoning from full text tags or metadata
        reasoning_block, cleaned = extract_tag_block(full_text, "reasoning_summary")
        if not reasoning_block:
            reasoning_block, cleaned = extract_tag_block(cleaned, "summary")

        if not reasoning_block and reasoning_meta:
            reasoning_block = reasoning_meta

        # Remove <final> block if present
        _, cleaned = extract_tag_block(cleaned, "final")

        content = content_buffer.strip()

        if not thoughts:
            thoughts = parse_reasoning_lines(reasoning_block)
            if thoughts:
                for t in thoughts:
                    yield {"type": "thoughts_delta", "thought": t}

        if thoughts:
            yield {"type": "thoughts", "thoughts": thoughts}

        yield {"type": "done", "content": content, "usage": last_usage, "thoughts": thoughts}
