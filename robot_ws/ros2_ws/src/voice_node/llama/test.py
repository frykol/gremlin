import ollama

def run_ollama_prompt(model_name: str, prompt: str):
    try:
        # Send a prompt to the local Ollama model
        response = ollama.chat(
            model=model_name,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        # Extract and return the model's reply
        return response['message']['content']
    except Exception as e:
        return f"Error: {e}"

model = "qwen2.5:1.5b-instruct"  # Make sure you have pulled this model: ollama pull llama3
user_prompt = """
You are a robot command parser.

Available intents:
forward
backward
full_left
full_right
left
right
spin
speed_up
slow_down
stop
unknown

Just give one word, that is the intention from the list.
Note that commands can be in Polish but answer in english.
If that the case first translate sentence to english and then choose intention.
Left means a turn to the left while full_left means driving to the left.

Example:
Command: "Jedź w lewo"
Answer: left

Command:
"Cała na lewo"
"""
output = run_ollama_prompt(model, user_prompt)
print("Model output:\n", output)