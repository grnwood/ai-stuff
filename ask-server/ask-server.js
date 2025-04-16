import express from 'express'
import cors from 'cors'
import dotenv from 'dotenv'
import fetch from 'node-fetch'

dotenv.config()

const app = express()
const PORT = process.env.PORT || 3000
const OPENAI_API_KEY = process.env.OPENAI_API_KEY
const API_SECRET_TOKEN = process.env.API_SECRET_TOKEN

if (!OPENAI_API_KEY || !API_SECRET_TOKEN) {
  console.error('❌ Missing OPENAI_API_KEY or API_SECRET_TOKEN in .env')
  process.exit(1)
}


app.use(cors())
app.use(express.json())

// 🔒 Token middleware
app.use((req, res, next) => {
  const token = req.headers['x-api-secret']
  if (!token || token !== API_SECRET_TOKEN) {
    return res.status(401).json({ error: 'Unauthorized: Invalid or missing secret token' })
  }
  next()
})

app.post('/chat', async (req, res) => {
    const { messages, model = 'gpt-3.5-turbo' } = req.body

  if (!messages || !Array.isArray(messages)) {
    return res.status(400).json({ error: 'Missing or invalid messages array' })
  }

  try {
    const openaiRes = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${OPENAI_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ model, messages }),
    })

    const data = await openaiRes.json()
    if (!openaiRes.ok) {
      return res.status(openaiRes.status).json(data)
    }

    res.json(data)
  } catch (error) {
    console.error('❌ Proxy Error:', error)
    res.status(500).json({ error: 'Proxy server error' })
  }
})

app.listen(PORT, () => {
  console.log(`🚀 Proxy running on http://localhost:${PORT}`)
})

/**
curl -X POST http://localhost:3000/chat \
  -H "Content-Type: application/json" \
  -H "x-api-secret: <token>" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [
      {"role": "user", "content": "Summarize this in 3 bullet points:\n\nToday I fixed a bug, helped QA, and deployed to staging."}
    ]
  }'
**/

