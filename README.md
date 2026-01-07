# Image Analysis with Gemini

This small utility lets you select images from your filesystem and sends them to a configured Gemini-like API for analysis.

Setup

1. Create a Python virtualenv and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. Set environment variables:

On Windows (PowerShell):

```powershell
$env:GEMINI_API_KEY = ""
```
or 

make a .env file where you will store you GEMINI_API_KEY

Usage

Run the GUI:

```bash
python image_analysis.py
```

Select images and click "Analyze Selected". Results show in the text pane.

Notes

- The script posts a simple JSON payload with a base64-encoded image. Adjust `image_analysis.py` to match your vendor's exact API spec.
- Keep your API keys secret.