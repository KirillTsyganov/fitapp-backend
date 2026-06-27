# 2. Start a workout session (use the id returned above)
curl -s -X POST http://localhost:5000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1}' | jq

# # 3. Log a set (use the session_id returned above)
# curl -s -X POST http://localhost:5000/api/sessions/1/sets \
#   -H "Content-Type: application/json" \
#   -d '{"reps": 20}' | jq

# # 4. Get user stats / dashboard
# curl -s http://localhost:5000/api/users/1/stats | jq