'use client'

interface SearchBarProps {
  query: string;
  setQuery: (query: string) => void;
  onSearch: (e: React.FormEvent) => void;
}

export default function SearchBar({ query, setQuery, onSearch }: SearchBarProps) {
  return (
    <form onSubmit={onSearch} className="mb-8">
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search articles..."
        className="w-full p-3 border rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
      />
    </form>
  )
}