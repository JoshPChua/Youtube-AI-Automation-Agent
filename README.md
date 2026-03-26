AI Video Agent — Autonomous Content Pipeline
An end-to-end, multi-agent AI workflow built in Python that autonomously generates, renders, and publishes YouTube Shorts.

This project orchestrates multiple AI APIs to handle topic selection, scriptwriting, voiceover generation, and video rendering, culminating in a fully automated upload sequence routed to specific YouTube channels.

System Architecture
The project is deliberately decoupled into two core components to ensure stability, prevent API timeouts, and allow for manual quality assurance when needed.

1. The Generation Engine (jpeeezy_agent.py)
A custom agentic workflow that handles the creative and rendering processes without manual intervention.

Orchestration: Claude AI manages the logical flow and multi-agent handoffs.

Scripting & Hooks: OpenAI GPT-4o generates viral-optimized scripts and metadata.

Visuals & Audio: OpenAI TTS generates natural voiceovers, while DALL-E 3 sources imagery.

Rendering: Creatomate API compiles the assets, applies captions, and renders the final HD MP4.

Notification: Telegram Bot API sends status updates and completion alerts to a mobile device.

2. The Decoupled Uploader (auto_uploader.py)
A standalone upload pipeline for locally saved or pre-generated videos.

Folder-Based Routing: Monitors a local ready_to_upload directory.

Publishing: Uses the YouTube Data API v3 to authenticate and upload the video to the correct channel with AI-generated titles and descriptions.

File Management: Automatically moves successfully published MP4s to an archive folder to prevent duplicate uploads.

Tech Stack
Language: Python

Development Environment: Antigravity IDE

AI & Logic: Claude API, OpenAI GPT-4o / DALL-E 3

Media Rendering: Creatomate API

Integrations: YouTube Data API v3, Google Sheets API, Telegram Bot API

Environment Management: python-dotenv

Installation & Setup
1. Clone the repository:
git clone https://github.com/JoshPChua/Youtube-AI-Automation-Agent.git

2. Install dependencies:
pip install -r requirements.txt

3. Configure Environment Variables:
Create a .env file in the root directory and add your API keys. (Do not upload this file or your JSON/Pickle OAuth tokens to GitHub).
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
CREATOMATE_API_KEY=your_key_here
TELEGRAM_BOT_TOKEN=your_token_here

4. Directory Structure:
Ensure the following local directories exist before running the uploader:

/ready_to_upload

/archive

Usage
To run the full generation pipeline:
python jpeeezy_agent.py

To run the standalone uploader for manually rendered files:
python auto_uploader.py
