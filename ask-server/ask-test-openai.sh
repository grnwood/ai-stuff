curl -X POST http://localhost:3000/chat \
  -H "Content-Type: application/json" \
  -H "x-api-secret: ohLa77354522192025Laq!" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "user", "content": "who are you?"},
      {"role": "user", "content": "tell me about rabbits?"}
        ],
    "stream": false
  }'

