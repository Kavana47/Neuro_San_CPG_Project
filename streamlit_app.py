"""
streamlit_app.py

A Streamlit frontend for the CPG Market Intelligence Neuro SAN agent
network. Talks to a running neuro-san server over its HTTP streaming_chat
API -- no gRPC or neuro-san client library dependency, just `requests`,
so this can run as a completely separate process/container from the
neuro-san server itself.

Neuro SAN HTTP API reference (see https://github.com/cognizant-ai-lab/neuro-san/blob/main/docs/clients.md):
    POST http://<host>:<port>/api/v1/<agent_network_name>/streaming_chat
    Body: {
        "user_message": {"text": "<user's message>"},
        "chat_context": {...}   # omit on first turn, then pass back what
                                 # the server returned, to continue the chat
    }
    The response is a stream of JSON chunks, each shaped like:
        {
            "response": {
                "type": "AGENT_FRAMEWORK",
                "text": "...",
                "chat_context": { ... }
            }
        }
    "AGENT_FRAMEWORK" is the type neuro-san uses for the frontman agent's
    final answer -- these are what we display to the user. The LAST such
    message's "chat_context" field is stored and sent back on the next
    turn to continue the conversation.

Run with:
    streamlit run streamlit_app.py

Requires the neuro-san server to already be running separately, e.g.:
    python -m run
(from your neuro-san-studio checkout, with this project's registries/
coded_tools wired in -- see the main README.md)
"""

import json
from typing import Any, Dict, Generator, Optional

import requests
import streamlit as st

from Report_Parser import render_structured_report

# ----------------------------------------------------------------------
# Page setup
# ----------------------------------------------------------------------
st.set_page_config(
    page_title="CPG Market Intelligence",
    page_icon="📊",
    layout="wide",
)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8080  # Neuro SAN server's HTTP port. NOT the nsflow UI port (4173) --
                      # nsflow is a React website for humans, it doesn't serve the API.
DEFAULT_AGENT_NAME = "basic/CPG_Market_Intelligence"


# ----------------------------------------------------------------------
# Session state
# ----------------------------------------------------------------------
def init_session_state() -> None:
    defaults = {
        "chat_history": [],       # list of {"role": "user"/"assistant", "text": ...}
        "chat_context": None,     # opaque continuation token from the server
        "last_error": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# ----------------------------------------------------------------------
# Neuro SAN HTTP client
# ----------------------------------------------------------------------
def build_streaming_chat_url(host: str, port: int, agent_name: str) -> str:
    return f"http://{host}:{port}/api/v1/{agent_name}/streaming_chat"


def stream_agent_response(
    host: str,
    port: int,
    agent_name: str,
    user_text: str,
    chat_context: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 120,
) -> Generator[Dict[str, Any], None, None]:
    """
    POSTs to the neuro-san streaming_chat endpoint and yields each parsed
    ChatMessage JSON object as it arrives. Raises requests exceptions on
    connection/timeout failure -- the caller is expected to catch them.
    """
    url = build_streaming_chat_url(host, port, agent_name)
    payload: Dict[str, Any] = {"user_message": {"text": user_text}}
    if chat_context:
        payload["chat_context"] = chat_context

    with requests.post(url, json=payload, stream=True, timeout=timeout_seconds) as response:
        response.raise_for_status()
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            # Some deployments prefix streamed lines with "data: " (SSE-style);
            # strip that if present before parsing JSON.
            if line.startswith("data:"):
                line = line[len("data:"):].strip()
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # Skip any non-JSON keep-alive/heartbeat lines rather than
                # crashing the whole stream.
                continue


def extract_ai_text_and_context(chat_message: Dict[str, Any]):
    """
    Given one parsed ChatMessage object from the stream, returns
    (text, chat_context) if this message is the frontman's answer,
    otherwise (None, None).

    Per the neuro-san HTTP streaming_chat API (docs/clients.md), each
    streamed chunk looks like:
        {
            "response": {
                "type": "AGENT_FRAMEWORK",
                "text": "...",
                "chat_context": { ... }
            }
        }
    "AGENT_FRAMEWORK" is the type neuro-san itself uses for the final
    answer coming back from the frontman agent. Earlier versions of this
    function checked for a bare top-level "type": "AI", which does not
    match this envelope shape -- that mismatch is why the app was falling
    through to the "No response text was found" message.

    This function unwraps the "response" envelope if present, and checks
    both "AGENT_FRAMEWORK" and a few other type strings some neuro-san
    versions/clients have used, so it stays robust across versions. If
    your server's response still doesn't match, expand "Raw stream
    (debug)" to see the exact shape and add it to KNOWN_ANSWER_TYPES below.
    """
    KNOWN_ANSWER_TYPES = ("AGENT_FRAMEWORK", "AI", "ai", "AGENT_FRAMEWORK_AI")

    # Unwrap the "response" envelope used by the HTTP streaming_chat API.
    inner = chat_message.get("response")
    message_obj = inner if isinstance(inner, dict) else chat_message

    msg_type = message_obj.get("type") or message_obj.get("message_type")
    if msg_type not in KNOWN_ANSWER_TYPES:
        return None, None

    text = message_obj.get("text")
    if text is None and isinstance(message_obj.get("message"), dict):
        text = message_obj["message"].get("text")
    context = message_obj.get("chat_context")
    return text, context


# ----------------------------------------------------------------------
# Sidebar: server connection + request scope
# ----------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Server connection")
    host = st.text_input("Host", value=DEFAULT_HOST)
    port = st.number_input(
        "Port",
        value=DEFAULT_PORT,
        min_value=1,
        max_value=65535,
        step=1,
        help=(
            "This is the Neuro SAN SERVER's port (default 8080), not the nsflow "
            "UI's port (default 4173). nsflow is a website for humans and doesn't "
            "answer API calls -- pointing this at 4173 causes a 405 error."
        ),
    )
    agent_name = st.text_input("Agent network name", value=DEFAULT_AGENT_NAME)

#    st.divider()
#    st.header("🔍 Analysis scope")
#    product = st.text_input("Product / category", placeholder="e.g. oat milk")
#    country = st.text_input("Country", value="India")
#    brands_raw = st.text_area(
#        "Brands (optional, one per line)",
#        placeholder="Leave blank to let the agent discover top brands automatically",
#        height=100,
#    )
#    time_range = st.selectbox(
#        "Time range",
#        ["last 3 months", "last 6 months", "last 12 months", "last month"],
#        index=2,
#    )

#    st.divider()
#    if st.button("🔄 Reset conversation", use_container_width=True):
#        st.session_state.chat_history = []
#        st.session_state.chat_context = None
#        st.session_state.last_error = None
#        st.rerun()


# ----------------------------------------------------------------------
# Main area
# ----------------------------------------------------------------------
st.title("📊 CPG Market Intelligence")
st.caption(
    "Multi-agent market trend, customer feedback, and competitive analysis, "
    "powered by a Neuro SAN agent network."
)

# Render existing chat history
for turn in st.session_state.chat_history:
    with st.chat_message(turn["role"]):
        if turn["role"] == "assistant" and turn.get("is_structured"):
            render_structured_report(turn["text"], turn.get("brands"))
        else:
            st.markdown(turn["text"])

# Structured "build a request" button, alongside free-form chat below
'''col1, col2 = st.columns([1, 3])
with col1:
    run_analysis = st.button("▶️ Run analysis", type="primary", use_container_width=True)

if run_analysis:
    if not product.strip():
        st.error("Please enter a product/category in the sidebar before running an analysis.")
    else:
        brands_list = [b.strip() for b in brands_raw.splitlines() if b.strip()]
        request_lines = [f"Analyze the {product.strip()} market in {country.strip() or 'India'}."]
        if brands_list:
            request_lines.append(f"Use these brands specifically: {', '.join(brands_list)}.")
        else:
            request_lines.append("Discover the top brands automatically.")
        request_lines.append(f"Use a time range of {time_range}.")
        user_text = " ".join(request_lines)

        st.session_state.chat_history.append({"role": "user", "text": user_text})
        with st.chat_message("user"):
            st.markdown(user_text)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            placeholder.markdown("_Contacting agent network..._")
            accumulated_text = ""
            final_context = st.session_state.chat_context
            debug_messages = []

            try:
                for chat_message in stream_agent_response(
                    host=host,
                    port=int(port),
                    agent_name=agent_name,
                    user_text=user_text,
                    chat_context=st.session_state.chat_context,
                ):
                    debug_messages.append(chat_message)
                    text, context = extract_ai_text_and_context(chat_message)
                    if text:
                        accumulated_text = text  # frontman messages are typically whole, not deltas
                        placeholder.markdown(accumulated_text)
                    if context:
                        final_context = context

                if not accumulated_text:
                    accumulated_text = (
                        "_No response text was found in the agent stream. Expand "
                        "'Raw stream (debug)' below to inspect what came back and "
                        "adjust `extract_ai_text_and_context()` if your neuro-san "
                        "version uses different field names._"
                    )
                    placeholder.markdown(accumulated_text)
                else:
                    # Replace the streaming placeholder with the structured,
                    # tabbed view now that we have the full report text.
                    placeholder.empty()
                    render_structured_report(accumulated_text, brands_list)

                st.session_state.chat_history.append(
                    {
                        "role": "assistant",
                        "text": accumulated_text,
                        "is_structured": bool(accumulated_text) and "No response text" not in accumulated_text,
                        "brands": brands_list,
                    }
                )
                st.session_state.chat_context = final_context
                st.session_state.last_error = None

                with st.expander("Raw stream (debug)"):
                    st.json(debug_messages)

            except requests.exceptions.ConnectionError:
                error_text = (
                    f"**Could not connect to the neuro-san server** at "
                    f"`http://{host}:{port}`.\n\n"
                    f"Make sure the server is running (`python -m run` from your "
                    f"neuro-san-studio checkout) and that the host/port in the "
                    f"sidebar match."
                )
                placeholder.markdown(error_text)
                st.session_state.last_error = error_text
            except requests.exceptions.Timeout:
                error_text = (
                    "**The request timed out** waiting for the agent network to "
                    "respond. Multi-brand portfolio analyses can take a while -- "
                    "try increasing `timeout_seconds` in `stream_agent_response()`, "
                    "or narrow the request (fewer brands / a single brand) and retry."
                )
                placeholder.markdown(error_text)
                st.session_state.last_error = error_text
            except requests.exceptions.HTTPError as e:
                if getattr(e.response, "status_code", None) == 405:
                    error_text = (
                        f"**405 Method Not Allowed.** This almost always means the "
                        f"Port in the sidebar is pointed at the **nsflow UI** "
                        f"(default `4173`) instead of the **Neuro SAN server** "
                        f"(default `8080`). nsflow is a website for humans and "
                        f"doesn't serve the `streaming_chat` API. Change Port to "
                        f"`8080` (or whatever `NEURO_SAN_SERVER_HTTP_PORT` is set "
                        f"to in your server's `.env`) and try again."
                    )
                else:
                    error_text = (
                        f"**Server returned an error:** `{e}`.\n\n"
                        f"Double-check that `{agent_name}` matches an entry in your "
                        f"`registries/manifest.hocon`."
                    )
                placeholder.markdown(error_text)
                st.session_state.last_error = error_text
            except Exception as e:
                error_text = f"**Unexpected error:** `{str(e)}`"
                placeholder.markdown(error_text)
                st.session_state.last_error = error_text
'''
st.divider()

# Free-form follow-up chat, using the same session/chat_context
follow_up = st.chat_input("Ask a follow-up question (e.g. 'What about pricing trends specifically?')")
if follow_up:
    st.session_state.chat_history.append({"role": "user", "text": follow_up})
    with st.chat_message("user"):
        st.markdown(follow_up)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown("_Thinking..._")
        accumulated_text = ""
        final_context = st.session_state.chat_context

        try:
            for chat_message in stream_agent_response(
                host=host,
                port=int(port),
                agent_name=agent_name,
                user_text=follow_up,
                chat_context=st.session_state.chat_context,
            ):
                text, context = extract_ai_text_and_context(chat_message)
                if text:
                    accumulated_text = text
                    placeholder.markdown(accumulated_text)
                if context:
                    final_context = context

            if not accumulated_text:
                accumulated_text = "_No response text found in the stream._"
                placeholder.markdown(accumulated_text)

            st.session_state.chat_history.append({"role": "assistant", "text": accumulated_text})
            st.session_state.chat_context = final_context

        except requests.exceptions.ConnectionError:
            placeholder.markdown(f"**Could not connect to the server** at `http://{host}:{port}`.")
        except requests.exceptions.HTTPError as e:
            if getattr(e.response, "status_code", None) == 405:
                placeholder.markdown(
                    "**405 Method Not Allowed.** Port is likely pointed at the "
                    "nsflow UI (`4173`) instead of the Neuro SAN server (`8080`). "
                    "Fix the Port in the sidebar."
                )
            else:
                placeholder.markdown(f"**Error:** `{str(e)}`")
        except Exception as e:
            placeholder.markdown(f"**Error:** `{str(e)}`")

if st.session_state.last_error:
    st.info(
        "If errors persist, verify the server is reachable directly, e.g.:\n\n"
        f"```bash\ncurl http://{host}:{port}/api/v1/{agent_name}/function\n```"
    )