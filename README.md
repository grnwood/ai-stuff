SlipstreamAI: Your Personal Gateway to OpenAI


  SlipstreamAI is a powerful and flexible software suite designed to provide a
  seamless and unrestricted chat experience with OpenAI's language models. It
  consists of two core components: a local proxy server and a feature-rich
  desktop GUI client.


  The primary purpose of this architecture is to bypass network restrictions that
   might prevent direct access to the OpenAI API. By routing requests through a
  local server, SlipstreamAI ensures you can connect from any environment,
  providing a stable and private bridge for all your interactions.

  Core Components


  1. The Proxy Server (ask-server.js)


  The heart of the suite is a lightweight and efficient Node.js proxy server. Its
   sole responsibility is to act as a secure intermediary between the desktop
  client and the OpenAI API.


   * Bypasses Network Restrictions: It receives requests from the client on your
     local machine and forwards them to OpenAI, effectively circumventing firewalls
      or network policies that block direct API access.
   * Secure & Streamlined: The server is protected by a secret token, ensuring that
      only your authorized client can use it. It handles the complexities of API
     communication, including support for streaming responses back to the client in
      real-time.
   * Model Discovery: It includes an endpoint to fetch the list of available models
      from OpenAI, which is then displayed in the client's UI.


  2. The Desktop Client (ask-client.py)


  The client is a sophisticated desktop application built with Python and
  Tkinter, offering a comprehensive and user-friendly interface for interacting
  with the AI models. It connects exclusively to the local proxy server, ensuring
   all communication is secure and private.

  ---

  Client Features


  SlipstreamAI is more than just a chat window. It's a full-featured environment
  designed to enhance your productivity and creativity.


   * 📂 Hierarchical Session Management: Organize your chats with nested folders.
     Keep your projects, research, and creative writing neatly separated and easy
     to find.


   * 🖱️ Intuitive Drag & Drop: Effortlessly reorder your chats and move them
     between folders with a simple drag-and-drop interface.


   * 🤖 AI-Powered Context Menu: This is where the magic happens. Right-click on
     any text in the chat history to instantly:
       * Summarize, Rephrase, or Elaborate: Condense long passages, rewrite text in
          a different tone (formal, informal), or expand on ideas.
       * Translate & Explain: Translate text between languages or ask for a simpler
          explanation of complex topics.
       * Analyze & Extract: Analyze sentiment, identify bias, or extract key points
          and action items from the text.
       * Generate & Define: Ask the AI to generate follow-up questions, define
         highlighted terms, or provide more context.


   * 🧠 Automatic Conversation Titling: Sessions are automatically renamed based on
      the topic of the conversation, saving you the hassle of naming them yourself.


   * 🎨 Customizable Interface: Tailor the look and feel to your preference with:
       * Light & Dark Themes: Switch between themes for comfortable viewing in any
         lighting.
       * Adjustable Fonts: Independently control the font and size for both the
         chat history and the general UI elements.


   * 📝 Dedicated System Prompt Panel: Fine-tune the AI's behavior for each session
      with a dedicated, resizable panel for your system prompts.


   * 🔄 Import & Export: Easily back up your conversations or share them with
     others by exporting chats to JSON files. You can also import chats to pick up
     where you left off.


   * 🔍 In-Chat Search: Quickly find specific information within a long
     conversation using the built-in search function (Ctrl+F).


   * 📜 Command History: Cycle through your previous inputs using the up and down
     arrow keys, just like in a terminal.
   * ⌨️ F2 Hotkey: Press F2 on a selected session to quickly rename it.
   * 🖋️ UI Font Customization: Choose both the font family and size for all interface elements.

---

## Proxy Server Deployment

SlipstreamAI's proxy server (`ask-server.js`) can be deployed locally or on a third-party always-on service for remote access. This flexibility allows you to run the server on your own machine or host it in the cloud for 24/7 availability.

### Local Deployment

To run the proxy server locally:

1. Install Node.js if you haven't already.
2. Navigate to the `ask-server` directory:
   ```bash
   cd ask-server
   ```
3. Install dependencies:
   ```bash
   npm install
   ```
4. Start the server:
   ```bash
   node ask-server.js
   ```
5. The server will listen on the default port (e.g., 3000). You can configure the port and secret token in the environment variables.

### Deploying on Render.com (Cloud Hosting Example)

You can quickly deploy the proxy server to [Render.com](https://render.com), a popular always-on cloud service. Here are general steps:

1. Create a free account at [render.com](https://render.com).
2. Click "New Web Service" and connect your GitHub repository containing `ask-server.js`.
3. Set the build command to:
   ```bash
   npm install
   ```
4. Set the start command to:
   ```bash
   node ask-server.js
   ```
5. Add environment variables for your OpenAI API key and secret token (e.g., `OPENAI_API_KEY`, `API_SECRET_TOKEN`).
6. Choose a region and deploy. Render will provide a public URL for your proxy server.

**Tip:** You can use similar steps for other cloud platforms that support Node.js (such as Heroku, Vercel, or Fly.io).

Once deployed, point your SlipstreamAI client to the new proxy server URL for remote access.

### Enabling HTTPS

`ask-server.js` can optionally run over HTTPS. Provide the paths to your SSL key and certificate via the `SSL_KEY_PATH` and `SSL_CERT_PATH` environment variables. If both are set, the server will listen with TLS enabled.

#### Self‑signed certificate

For local testing you can generate a self‑signed certificate:

```bash
openssl req -x509 -newkey rsa:4096 -nodes -keyout key.pem -out cert.pem -days 365
```

Set the variables and start the server:

```bash
export SSL_KEY_PATH=$(pwd)/key.pem
export SSL_CERT_PATH=$(pwd)/cert.pem
node ask-server.js
```

#### Using a real certificate

On a public server you can obtain a free certificate from [Let’s Encrypt](https://letsencrypt.org/). Tools like [Certbot](https://certbot.eff.org/) automate the process:

```bash
sudo certbot certonly --standalone -d yourdomain.com
```

After issuance, set `SSL_KEY_PATH` to the private key file and `SSL_CERT_PATH` to the full chain certificate provided by Certbot. Restart `ask-server.js` and update your client’s `OPENAI_PROXY_URL` to use `https://`.

---

TESSERACT
If you want to install tesseract to have PDF OCR capability the the binary and the python wrapper need to be installed.
See README-tessaract-windows.md
add the path to the binary to the env file.


for *nix it's easy:

$ sudo apt install tesseract-ocr

