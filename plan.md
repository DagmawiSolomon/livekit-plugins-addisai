1. [x] Remove per‑chunk re‑encoding overhead — avoid pydub if possible. Decode WAV directly and stream raw PCM to reduce latency and CPU spikes.
2. [x] Reuse the AsyncClient instead of creating one per request.
3. [x] Implement retry/backoff using conn_options for transient 5xx/timeout errors.
4. [x] Chunk smoothing — buffer small PCM fragments before push() to avoid jitter.
5. Backpressure awareness — stop reading if the emitter is closed (interruption).
6. Validate sample rate consistency with output_emitter.initialize().
7. Robust Error handling 
   - Retries
   - Proper Exception mapping
   - Safe Json Parsing for streaming data
8. Sharing HTTP clients across requests to benefit from connection pooling and potentially optimizing audio transcoding
9. Observability: Integrating structured logging and performance metrics.
