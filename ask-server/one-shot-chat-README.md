Try it like this (fills in everything explicitly):

python3 ask-server/one-shot-chat.py \
  "s:'lm studio' md:'ibm/granite-4-h-tiny' p:'You are a concise assistant.' \
   c:'12345' m:'What is the weather in Seattle today?'"


Only m: is required; if you omit the others the script will pull the defaults from /models.git s