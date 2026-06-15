import uvicorn

if __name__ == "__main__":
    # Start the development server on http://localhost:8000
    # reload=True restarts the server automatically whenever you save a file
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
