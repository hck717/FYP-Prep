# src/llm/perplexity_client.py
import os
import json
from typing import List, Dict, Any, Optional, Union, Tuple
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
    temperature: float = 0.0,
    return_citations: bool = False
) -> Union[str, Tuple[str, List[str]]]:
    """
    Call Perplexity API using OpenAI-compatible client.
    Matches the official pattern: client = OpenAI(api_key=..., base_url="https://api.perplexity.ai")
    
    Args:
        api_key: PPLX API Key
        messages: Chat history
        model: Model name (default: sonar-pro)
        temperature: 0.0 for deterministic
        return_citations: If True, returns (content, citations_list)
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
        
        if return_citations:
            citations = getattr(response, 'citations', [])
            return (content or ""), citations
            
        return content or ""

    except Exception as e:
        print(f"Perplexity API Call Failed: {e}")
        # Re-raise or handle gracefully depending on caller preference
        raise e
