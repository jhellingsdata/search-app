'use client'
import { useState } from 'react'
import SearchBar from '@/components/SearchBar'
import ResultCard from '@/components/ResultCard'

interface SearchResult {
  title: string;
  url: string;
  teaser: string;
  date: string;
  main_category: string;
}

export default function Home() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return
    
    setLoading(true)
    try {
      const response = await fetch('/api/search', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: query,
          top_k: 5
        })
      })
      const data = await response.json()
      setResults(data.results)
    } catch (error) {
      console.error('Search failed:', error)
    }
    setLoading(false)
  }

  return (
    <main className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold mb-8">Economics Observatory Search</h1>
      
      <SearchBar 
        query={query}
        setQuery={setQuery}
        onSearch={handleSearch}
      />

      {loading ? (
        <div className="text-center py-8">Loading...</div>
      ) : (
        <div>
          {results.map((result, index) => (
            <ResultCard
              key={index}
              title={result.title}
              teaser={result.teaser}
              url={result.url}
              date={result.date}
              category={result.main_category}
            />
          ))}
        </div>
      )}
    </main>
  )
}