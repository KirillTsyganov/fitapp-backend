# 1. Create a user
curl -s -X POST http://localhost:5000/api/users \
  -H "Content-Type: application/json" \
  -d '{"username": "Kirill", "email": "kirill@example.com"}' | jq