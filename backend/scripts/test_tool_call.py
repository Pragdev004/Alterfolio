from app.services.ai.ai_service import AIService

ai = AIService()

response = ai.create_tool_response(
    "What does my portfolio look like?"
)

print("=" * 80)
print("RAW RESPONSE")
print("=" * 80)

print(response)

print()

print("=" * 80)
print("OUTPUT ITEMS")
print("=" * 80)

for item in response.output:
    print(item)
    print("-" * 80)