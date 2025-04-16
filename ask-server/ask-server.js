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

// 🔐 Auth middleware
app.use((req, res, next) => {
  const token = req.headers['x-api-secret']
  if (!token || token !== API_SECRET_TOKEN) {
    return res.status(401).json({ error: 'Unauthorized: Invalid or missing secret token' })
  }
  next()
})

// 🎯 POST /chat (with optional streaming)
app.post('/chat', async (req, res) => {
  const {
    model = 'gpt-3.5-turbo',
    system = null,
    prompt = '',
    ai = '',
    stream = false
  } = req.body

  if (!prompt && !ai) {
    return res.status(400).json({ error: 'Missing both prompt and ai content' })
  }

  const messages = []
  console.log("Incoming request body:", req.body);

  if (system) {
    messages.push({ role: 'system', content: system.trim() })
  }

  const userContent = prompt ? `${prompt.trim()}\n\n${ai.trim()}` : ai.trim()
  messages.push({ role: 'user', content: userContent })

  const openaiPayload = {
    model,
    messages,
    stream
  }

  try {
    const openaiRes = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${OPENAI_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(openaiPayload)
    })

    if (!stream) {
      const data = await openaiRes.json()
      return res.status(openaiRes.status).json(data)
    }

    // Stream mode
    res.setHeader('Content-Type', 'text/event-stream')
    res.setHeader('Cache-Control', 'no-cache')
    res.setHeader('Connection', 'keep-alive')

    openaiRes.body.on('data', chunk => {
      res.write(chunk)
    })

    openaiRes.body.on('end', () => {
      res.end()
    })

    openaiRes.body.on('error', (err) => {
      console.error('❌ Stream error from OpenAI:', err)
      res.write(`data: [ERROR] ${err.message}\n\n`)
      res.end()
    })

  } catch (err) {
    console.error('❌ Proxy error:', err)
    res.status(500).json({ error: 'Proxy server error' })
  }
})

app.listen(PORT, () => {
  console.log(`🚀 Proxy running with streaming at http://localhost:${PORT}`)
})

