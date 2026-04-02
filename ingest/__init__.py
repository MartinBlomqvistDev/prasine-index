# Ingest modules for the Prasine Index pipeline. Each module is responsible
# for querying one EU open data source and returning typed Evidence records.
# All ingest functions are async and designed to be called in parallel via
# asyncio.gather() within the LangGraph Verification Agent graph.
