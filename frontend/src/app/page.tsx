'use client'
import { useState, useMemo } from 'react'
import SearchBar from '@/components/SearchBar'
import ResultCard from '@/components/ResultCard'
import DateBrushFilter from '@/components/DateBrushFilter'
import articlesData from '@/data/articles.json'

interface SearchResult {
  title: string;
  url: string;
  teaser: string;
  date: string;
  main_category: string;
}

interface ArticleMetadata {
  title: string;
  date: string;
  slug: string;
  url: string;
}

export default function Home() {
  const [query, setQuery] = useState('')
  const [allResults, setAllResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)

  // Date range state
  const minDate = '2020-05-01'
  const currentDate = new Date().toISOString().split('T')[0];
  const [dateFrom, setDateFrom] = useState(minDate);
  const [dateTo, setDateTo] = useState(currentDate);

  // Convert articles object to array
  const allArticles = useMemo(() => {
    return Object.values(articlesData as Record<string, ArticleMetadata>)
      .map(article => ({
        title: article.title,
        date: article.date
      }))
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
  }, [])

  // Filter results based on date range
  const filteredResults = useMemo(() => {
    return allResults.filter(result => {
      const resultDate = new Date(result.date).getTime()
      const fromDate = new Date(dateFrom).getTime()
      const toDate = new Date(dateTo).getTime()
      return resultDate >= fromDate && resultDate <= toDate
    })
  }, [allResults, dateFrom, dateTo])

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
          top_k: 15,
          date_from: dateFrom,
          date_to: dateTo
        })
      })
      const data = await response.json()
      setAllResults(data.results)
    } catch (error) {
      console.error('Search failed:', error)
    }
    setLoading(false)
  }

  // Handle date range changes
  const handleDateRangeChange = (start: string, end: string) => {
    setDateFrom(start)
    setDateTo(end)
  }

  // Match search results with all articles for highlighting
  const matchedSearchResults = useMemo(() => {
    return allResults.map(result => {
      // Extract slug from URL if needed for matching
      const resultSlug = result.url.split('/').pop() || ''
      
      // Try to match by URL, slug, or title
      const matchedArticle = Object.values(articlesData as Record<string, ArticleMetadata>).find(
        article => 
          article.url === result.url || 
          article.slug === resultSlug ||
          article.title === result.title
      )
      
      return {
        title: matchedArticle?.title || result.title,
        date: matchedArticle?.date || result.date
      }
    })
  }, [allResults])

  return (
    <main className="container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold mb-8">Economics Observatory Search</h1>
      
      <SearchBar 
        query={query}
        setQuery={setQuery}
        onSearch={handleSearch}
      />

      <DateBrushFilter
        minDate={dateFrom}
        maxDate={dateTo}
        articles={allArticles}
        searchResults={matchedSearchResults}
        onChange={handleDateRangeChange}
      />

      {query && (
        <div className="mb-4 text-sm text-gray-600">
          Showing {filteredResults.length} of {allResults.length} results
          {filteredResults.length !== allResults.length && ' (filtered by date)'}
        </div>
      )}

      {loading ? (
        <div className="text-center py-8">Loading...</div>
      ) : (
        <div>
          {filteredResults.map((result, index) => (
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