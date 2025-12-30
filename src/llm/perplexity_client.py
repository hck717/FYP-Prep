# src/llm/perplexity_client.py
import os
import json
from typing import List, Dict, Any
from openai import OpenAI

# Updated to a valid model as of late 2025/early 2026
MODEL_NAME = "sonar-pro"

def call_perplexity(api_key: str, messages: List[Dict[str, str]]) -> str:
    """
    Call Perplexity API using OpenAI-compatible client.
    """
    client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
    
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.0,
    )
    
    return response.choices[0].message.content
