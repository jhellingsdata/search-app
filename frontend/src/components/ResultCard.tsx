import categoryColours from "@/lib/categoryColours";

interface ResultCardProps {
    title: string;
    teaser: string;
    url: string;
    date: string;
    category: string;
  }
  
  export default function ResultCard({ title, teaser, url, date, category }: ResultCardProps) {
    const categoryColour = categoryColours[category]?.colour || "#ccc"; // Fallback color
    const categoryClass = categoryColours[category]?.class || "";

    return (
      <div className="mb-4 p-4 border rounded-lg hover:shadow-md transition-shadow bg-[#f7f7f7]">
        <h2 className="text-xl font-semibold mb-2">
          <a href={url} target="_blank" rel="noopener noreferrer" className="text-[#122B39] hover:text-[#E6224B] ease-in-out duration-300">
            {title}
          </a>
        </h2>
        <p className="text-gray-600 mb-2">{teaser}</p>
        <div className="flex text-sm text-gray-500">
          <span>{date}</span>
          <span className="mx-2">•</span>
          <span 
            className={`${categoryClass}`} 
            style={{ color: categoryColour }}>
            {category.toUpperCase()}
          </span>
        </div>
      </div>
    )
  }