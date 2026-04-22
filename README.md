# AddisAI LiveKit Plugins

> [!CAUTION]
> **This project is currently under active development.**
> It is not yet optimized for performance or hardened for production use. Expect potential bugs and lack of fault tolerance.

This repository provides LiveKit plugins for [AddisAI](https://addisai.ch/)'s STT (Speech-to-Text) and TTS (Text-to-Speech)

## Setup Guide

Follow these steps to set up the AddisAI plugin with a LiveKit.

### 1. Prerequisites

- [Python 3.10+](https://www.python.org/downloads/)
- [uv](https://github.com/astral-sh/uv) (recommended for fast package management)
### 2. Clone the Repositories

First, clone this plugin repository:

```bash
git clone https://github.com/DagmawiSolomon/livekit-plugins-addisai
```

Then, clone the LiveKit Agent Starter (Python) repository into a separate folder:

```bash
git clone https://github.com/livekit-examples/agent-starter-python
```

### 3. Environment Setup

Navigate to the `agent-starter-python` directory

```bash
cd agent-starter-python
```

Install the dependencies:

```bash
uv sync
```

### 4. Plugin Installation

Add the `livekit-plugins-addisai` package to your project by providing the path to your local clone:

```bash
uv add ../livekit-plugins-addisai
```

### 5. Configuration

Create a `.env.local` file in the `agent-starter-python` directory and add your credentials:

> [!IMPORTANT]
> Use `.env.local` as the filename or ensure you update the `load_dotenv` call in `src/agent.py`, as the starter repo is configured to load `.env.local` by default.

```env
LIVEKIT_URL=<your-livekit-url>
LIVEKIT_API_KEY=<your-api-key>
LIVEKIT_API_SECRET=<your-api-secret>

# AddisAI Credentials
ADDISAI_API_KEY=<your-addisai-api-key>
```

### 6. Quick Start Example

You can use the AddisAI plugin in your agent by importing it and configuring it within your `AgentSession`:

```python
from livekit.plugins import addisai
from livekit.agents import AgentSession

# ... inside your agent worker (e.g., my_agent function) ...
async def my_agent(ctx: JobContext):
    # Set up the AgentSession with AddisAI components for Amharic
    session = AgentSession(
        # AddisAI STT for Amharic
        stt=addisai.STT(language="am"),
        llm=inference.LLM(model="openai/gpt-4.1-mini"),
        # AddisAI TTS for Amharic
        tts=addisai.TTS(language="am"),
    )

    # Start the session with your Assistant agent
    await session.start(agent=Assistant(), room=ctx.room)
```

Run your agent:

```bash
uv run .\src\agent.py console
```
