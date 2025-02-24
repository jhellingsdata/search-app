import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  const body = await request.json();
  
  try {
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/search`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('API proxy error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch from API' },
      { status: 500 }
    );
  }
}