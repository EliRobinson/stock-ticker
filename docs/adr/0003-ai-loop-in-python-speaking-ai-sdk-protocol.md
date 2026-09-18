# AI loop runs in Python, streaming the AI SDK protocol

The frontend uses the Vercel AI SDK's `useChat` and its UI components. The obvious way to use it is to run the model loop in a Next.js route handler with AI SDK Core. Instead, the FastAPI backend runs the Claude tool loop and streams its replies in the AI SDK's documented UI message stream protocol. This follows the brief's rule that the backend is Python. It also keeps the SQL tool in the same process as the read-only database connection it depends on. The cost is maintaining that stream format by hand in Python.
