# src/llm/perplexity_client.py
import os
import json
from typing import List, Dict, Any, Optional
from openai import OpenAI

# Valid models as of late 2025:
# "sonar" (Standard)
# "sonar-pro" (Advanced - Recommended for complex tasks)
# "sonar-reasoning" (Reasoning Standard)
# "sonar-reasoning-pro" (Reasoning Advanced)
MODEL_NAME = "sonar-pro"

def call_perplexity(
    api_key: str, 
    messages: List[Dict[str, str]],
    model: str = MODEL_NAME,
    temperature: float = 0.0
) -> str:
    """
    Call Perplexity API using OpenAI-compatible client.
    Matches the official pattern: client = OpenAI(api_key=..., base_url="https://api.perplexity.ai")
    
    Defaults:
    - model: sonar-pro
    - temperature: 0.0 (Deterministic output)
    """
    if not api_key:
        raise ValueError("Perplexity API key is required.")

    client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        
        # Robustly extract content
        content = response.choices[0].message.content
        if not content:
            return ""
            
        return content

    except Exception as e:
        print(f"Perplexity API Call Failed: {e}")
        # Re-raise or handle gracefully depending on caller preference
        raise e
