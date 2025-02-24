interface ResultCardProps {
    title: string;
    teaser: string;
    url: string;
    date: string;
    category: string;
  }
  
  export default function ResultCard({ title, teaser, url, date, category }: ResultCardProps) {
    return (
      <div className="mb-4 p-4 border rounded-lg hover:shadow-md transition-shadow">
        <h2 className="text-xl font-semibold mb-2">
          <a href={url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:text-blue-800">
            {title}
          </a>
        </h2>
        <p className="text-gray-600 mb-2">{teaser}</p>
        <div className="flex text-sm text-gray-500">
          <span>{date}</span>
          <span className="mx-2">•</span>
          <span>{category}</span>
        </div>
      </div>
    )
  }