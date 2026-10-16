export function GET() {
  return Response.json(
    { status: "healthy", service: "floodguard-frontend" },
    {
      headers: { "Cache-Control": "no-store" },
    },
  );
}
