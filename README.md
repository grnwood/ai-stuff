
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

## RAG Support

SlipstreamAI optionally integrates with [ChromaDB](https://docs.trychroma.com/) for
retrieval‑augmented generation (RAG). When a RAG database is loaded, the
application now ensures that the underlying Chroma client is shut down whenever
you close the program or switch databases. This prevents lingering background
processes from consuming memory.