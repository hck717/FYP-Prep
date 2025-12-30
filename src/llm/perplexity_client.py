import os
from openai import OpenAI

def call_perplexity(api_key: str, messages: list, model: str = "llama-3.1-sonar-large-128k-online") -> str:
    """
    Calls Perplexity API using the OpenAI-compatible client.
    """
    client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
    
    response = client.chat.completions.create(
        model=model,
        messages=messages,
    )
    
    return response.choices[0].message.content