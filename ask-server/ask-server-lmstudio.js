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

// 🎯 Chat endpoint
app.post('/chat', async (req, res) => {
  const isOpenAISpec = Array.isArray(req.body.messages)
  const stream = req.body.stream === true
  let payload = {}
    console.log('handling message' +JSON.stringify(req.body))
  if (isOpenAISpec) {
    // ✅ OpenAI spec format
    const { model, messages, ...rest } = req.body
    if (!model || !messages) {
      return res.status(400).json({ error: 'Missing required fields: model or messages' })
    }
    payload = {
      model,
      messages,
      stream,
      ...Object.fromEntries(Object.entries(rest).filter(([k]) => k !== 'session_id'))
    }

  } else {
    // ✅ Custom format (ask.py style)
    const {
      model = 'gpt-3.5-turbo',
      prompt = '',
      ai = '',
      system = null,
      ...rest
    } = req.body

    if (!prompt && !ai) {
      return res.status(400).json({ error: 'Missing both prompt and ai content' })
    }

    const messages = []
    if (system) messages.push({ role: 'system', content: system.trim() })

    const userMessage = prompt ? `${prompt.trim()}\n\n${ai.trim()}` : ai.trim()
    messages.push({ role: 'user', content: userMessage })

    payload = { model, messages, stream, ...rest }
  }

  try {
    const openaiRes = await fetch('https://api.openai.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${OPENAI_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload)
    })

    if (!stream) {
      const data = await openaiRes.json()
console.log("resp: "+JSON.stringify(data))
      return res.status(openaiRes.status).json(data)
    }

    // 🔁 Streamed response
    res.setHeader('Content-Type', 'text/event-stream')
    res.setHeader('Cache-Control', 'no-cache')
    res.setHeader('Connection', 'keep-alive')

    openaiRes.body.on('data', chunk => {
      res.write(chunk)
    })

    openaiRes.body.on('end', () => res.end())

    openaiRes.body.on('error', err => {
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
  console.log(`🚀 ask-server ready on http://localhost:${PORT}`)
})

