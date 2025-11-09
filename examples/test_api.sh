#!/bin/bash

echo "Testing Polyglot Codebase APIs"
echo "================================"

echo -e "\n1. Testing Go Service Health:"
curl -s http://localhost:8080/health | jq .

echo -e "\n2. Testing Python Service Health:"
curl -s http://localhost:8081/health | jq .

echo -e "\n3. Testing Ruby Service Health:"
curl -s http://localhost:8082/health | jq .

echo -e "\n4. Testing Ruby Service Status (all services):"
curl -s http://localhost:8082/status | jq .

echo -e "\n5. Testing Code Analysis:"
curl -s -X POST http://localhost:8082/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "content": "def hello():\n    print(\"Hello, World!\")\n    return True",
    "path": "hello.py"
  }' | jq .

echo -e "\n6. Testing Code Metrics:"
curl -s -X POST http://localhost:8082/metrics \
  -H "Content-Type: application/json" \
  -d '{
    "content": "package main\n\nimport \"fmt\"\n\nfunc main() {\n    fmt.Println(\"Hello\")\n}"
  }' | jq .

echo -e "\nDone!"

