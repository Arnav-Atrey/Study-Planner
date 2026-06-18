import os
from typing import List, Dict, Tuple
import google.generativeai as genai
from dotenv import load_dotenv
from duckduckgo_search import DDGS

# Load environment variables
load_dotenv()

# Gemini chat history format: list of {"role": "user"|"model", "parts": [text]}
def _build_gemini_history(messages: List[Tuple[str, str]]) -> List[Dict]:
    """Convert list of (role, content) to Gemini chat history format."""
    history = []
    for role, content in messages:
        gemini_role = "user" if role == "user" else "model"
        history.append({"role": gemini_role, "parts": [content or ""]})
    return history

# function uses a query string and duckduckgo_search library to perform a web search
def perform_web_search(query: str, max_results: int = 6) -> List[Dict[str, str]]:
    """Perform a DuckDuckGo search and return a list of results.

    Each result contains: title, href, body.
    """
    results: List[Dict[str, str]] = []
    try:
        with DDGS() as ddgs:
            for result in ddgs.text(query, max_results=max_results):
                # result keys typically include: title, href, body
                if not isinstance(result, dict):
                    continue
                title = result.get('title') or ''
                href = result.get('href') or ''
                body = result.get('body') or ''
                if title and href:
                    results.append({
                        'title': title,
                        'href': href,
                        'body': body,
                    })
        return results
    except Exception as e:
        print(f"DuckDuckGo search error: {e}")
        return []

 # A class that manages the interaction with the Gemini API and core agent logic
class GeminiClient:
    def __init__(self):
        try:
            genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
            self.model = genai.GenerativeModel('gemini-flash-latest')
        except Exception as e:
            print(f"Error configuring Gemini API: {e}")
            self.model = None

    def generate_response(
        self,
        user_input: str,
        history: List[Tuple[str, str]] | None = None,
    ) -> str:
        """Generate an AI response with optional web search when prefixed.

        history: optional list of (role, content) with role 'user' or 'assistant'
        for conversation context. Used for multi-user persistent chats.

        To trigger web search, start your message with one of:
        - "search: <query>"
        - "/search <query>"
        """
        if not self.model:
            return "AI service is not configured correctly."

        try:
            text = user_input or ""
            lower = text.strip().lower()
            history = history or []

            # Build chat with prior history (Gemini expects user/model alternating)
            gemini_history = _build_gemini_history(history)
            chat = self.model.start_chat(history=gemini_history)

            # Search trigger
            search_query = None
            if lower.startswith("search:"):
                search_query = text.split(":", 1)[1].strip()
            elif lower.startswith("/search "):
                search_query = text.split(" ", 1)[1].strip()

            if search_query:
                web_results = perform_web_search(search_query, max_results=6)
                if not web_results:
                    return "I could not retrieve web results right now. Please try again."

                refs_lines = []
                for idx, item in enumerate(web_results, start=1):
                    refs_lines.append(f"[{idx}] {item['title']} — {item['href']}\n{item['body']}")
                refs_block = "\n\n".join(refs_lines)

                system_prompt = (
                    "You are an AI research assistant. Use the provided web search results to answer the user query. "
                    "Synthesize concisely, cite sources inline like [1], [2] where relevant, and include a brief summary."
                )
                composed = (
                    f"<system>\n{system_prompt}\n</system>\n"
                    f"<user_query>\n{search_query}\n</user_query>\n"
                    f"<web_results>\n{refs_block}\n</web_results>"
                )
                response = chat.send_message(composed)
                return response.text

            # Default: normal chat with history
            response = chat.send_message(text)
            return response.text
        except Exception as e:
            print(f"Error generating response: {e}")
            return "I'm sorry, I encountered an error processing your request."