'use client';

import React, { useEffect, useRef, useState, useMemo } from 'react';
import * as d3 from 'd3';

interface Article {
  date: string;
  title: string;
}

interface DateBrushFilterProps {
  minDate: string;
  maxDate: string;
  articles?: Article[];
  searchResults?: Article[];
  onChange?: (dateFrom: string, dateTo: string) => void;
}

const DateBrushFilter: React.FC<DateBrushFilterProps> = ({
  minDate,
  maxDate,
  articles = [],
  searchResults = [],
  onChange
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectedRange, setSelectedRange] = useState<{start: string | null, end: string | null}>({
    start: minDate,
    end: maxDate
  });
  const [isMounted, setIsMounted] = useState(false);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  // Generate random y positions once and memoize them
  const articlePositions = useMemo(() => {
    const yRandom = d3.randomNormal(0.5, 0.15); // Normalized to 0-1 range
    return articles.map(article => ({
      ...article,
      yPosition: Math.max(0.1, Math.min(0.9, yRandom())) // Clamp between 0.1 and 0.9
    }));
  }, [articles]);
  
  // Update selected range when props change
  useEffect(() => {
    setSelectedRange({
      start: minDate,
      end: maxDate
    });
  }, [minDate, maxDate]);
  
  // Set mounted state and handle resize
  useEffect(() => {
    setIsMounted(true);
    
    const updateDimensions = () => {
      if (containerRef.current) {
        const { width } = containerRef.current.getBoundingClientRect();
        setDimensions({
          width: width,
          height: 130 // Keep height fixed
        });
      }
    };
    
    // Initial dimension setting
    updateDimensions();
    
    // Set up resize observer
    const resizeObserver = new ResizeObserver(updateDimensions);
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }
    
    // Also listen to window resize as backup
    window.addEventListener('resize', updateDimensions);
    
    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', updateDimensions);
    };
  }, []);
  
  // Format date for display
  const formatDateDisplay = (dateStr: string) => {
    const date = new Date(dateStr);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };
  
  // Convert Date to string in YYYY-MM-DD format
  const dateToString = (date: Date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };
  
  useEffect(() => {
    if (!svgRef.current || !isMounted || dimensions.width === 0) return;
    
    // Clear any existing content
    d3.select(svgRef.current).selectAll("*").remove();
    
    // Set dimensions and margins
    const margin = { top: 20, right: 20, bottom: 40, left: 20 };
    const width = Math.max(300, dimensions.width) - margin.left - margin.right; // Min width of 300px
    const height = dimensions.height - margin.top - margin.bottom;
    
    // Create SVG
    const svg = d3.select(svgRef.current)
      .attr('width', width + margin.left + margin.right)
      .attr('height', height + margin.top + margin.bottom);
    
    // Create main group element
    const g = svg.append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`);
    
    // Define date range
    const domainStart = new Date('2020-05-01');
    const domainEnd = new Date();
    // domainEnd.setHours(0, 0, 0, 0); // Normalize to start of day, this breaks the brush
    
    // Create x scale
    const xScale = d3.scaleTime()
      .domain([domainStart, domainEnd])
      .range([0, width]);

    const yScale = d3.scaleLinear()
      .domain([0, 1])
      .range([height, 0]);
    
    
    // Create x axis with responsive tick formatting
    const tickFormat = width < 400
      ? d3.timeFormat('%Y') // Just year on very small screens
      : d3.timeFormat('%b %Y'); // Full year-month on larger screens
    
    const xAxis = d3.axisBottom(xScale)
      // Type assertion needed due to D3's overloaded tickFormat signature
      .tickFormat((d) => tickFormat(d as Date))
      .ticks(width < 500 ? d3.timeYear.every(1) : d3.timeMonth.every(6)); // Fewer ticks on mobile
    
    // Add x axis to chart
    g.append('g')
      .attr('class', 'x-axis')
      .attr('transform', `translate(0,${height})`)
      .call(xAxis)
      .selectAll('text')
      // .style('text-anchor', width < 400 ? 'middle' : 'midd')
      .style('text-anchor', 'middle')
      .style('fill', '#6b7280')
      // .attr('transform', width < 400 ? 'rotate(0)' : 'rotate(-45)')
      // .attr('dx', width < 400 ? '0' : '-0.8em')
      // .attr('dy', width < 400 ? '0.71em' : '0.15em');
    
    // Add a background rectangle for visual reference
    g.append('rect')
      .attr('class', 'background')
      .attr('x', 0)
      .attr('y', 0)
      .attr('width', width)
      .attr('height', height)
      .attr('fill', '#f0f0f0')
      .attr('stroke', '#ddd');

    // Create dots group (no transform needed)
    const dotsGroup = g.append('g')
        .attr('class', 'dots-group')
        .attr('fill-opacity', 0.8);

    // Add dots for articles
    dotsGroup.selectAll('circle')
        .data(articlePositions)
        .join('circle')
        // .attr('class', 'article-dot')
        .attr('class', d => {
          const isSearchResult = searchResults.some(r => 
              r.title === d.title && r.date === d.date
          );
          return isSearchResult ? 'article-dot article-dot-selected' : 'article-dot';
      })
        .attr('cx', d => xScale(new Date(d.date)))
        .attr('cy', d => yScale(d.yPosition))
        .attr('r', d => {
          const isSearchResult = searchResults.some(r => 
              r.title === d.title && r.date === d.date
          );
          return isSearchResult ? 3.5 : 2;
      })
        .attr('fill', d => {
            const isSearchResult = searchResults.some(r => 
                r.title === d.title && r.date === d.date
            );
            return isSearchResult ? '#ef4444' : '#6b7280';
        })
    
    // Create brush
    const brush = d3.brushX()
      .extent([[0, 0], [width, height]])
      .on('start brush end', function(event) {
        const selection = event.selection;
        
        if (selection) {
          // Convert pixel positions to dates
          const [x0, x1] = selection;
          const startDate = xScale.invert(x0);
          const endDate = xScale.invert(x1);
          
          // Convert dates to strings
          const startStr = dateToString(startDate);
          const endStr = dateToString(endDate);
          
          // Update visual feedback
          d3.select(this).select('.selection')
            .attr('fill', '#3b82f6')
            .attr('fill-opacity', 0.3);
          
          // Update state during brushing for immediate feedback
          if (event.type === 'brush' || event.type === 'end') {
            setSelectedRange({ start: startStr, end: endStr });
          }
          
          // Call the handler on brush end
          if (event.type === 'end' && onChange) {
            onChange(startStr, endStr);
            console.log('Date range selected:', startStr, 'to', endStr);
          }
        } else if (event.type === 'end') {
          // Brush was cleared - reset to full range
          const resetStart = '2020-05-01';
          const resetEnd = dateToString(new Date());
          setSelectedRange({ start: resetStart, end: resetEnd });
          if (onChange) {
            onChange(resetStart, resetEnd);
          }
          console.log('Date range cleared - reset to full range');
        }
      });
    
    // Add brush to the chart
    const brushGroup = g.append('g')
      .attr('class', 'brush')
      .call(brush);

    // brushGroup.call(brush.handleSize, '8px'); // Make handles slightly larger for easier grabbing
    
    // Style the brush handles
    brushGroup.selectAll('.handle')
      .attr('fill', '#3b82f6')
      // .style('width', '8px')
      .attr('fill-opacity', 0.6);
    
    // Style the brush overlay and selection
    brushGroup.select('.overlay')
      .style('cursor', 'crosshair');
    
    brushGroup.selectAll('.handle')
      .style('cursor', 'ew-resize');
    
    brushGroup.select('.selection')
      .attr('stroke', '#3b82f6')
      .attr('stroke-width', 1.5);
    
    // Initialize brush with provided dates
    const minDateObj = new Date(minDate);
    const maxDateObj = new Date(maxDate);
    
    // Only set initial brush if dates are within domain
    if (minDateObj >= domainStart && maxDateObj <= domainEnd) {
      // Type as tuple to satisfy D3's BrushSelection type
      const initialSelection: [number, number] = [
        xScale(minDateObj),
        xScale(maxDateObj)
      ];
      brushGroup.call(brush.move, initialSelection);
    }
    
    // Log to verify setup
    console.log('Chart initialized with selection:', minDate, 'to', maxDate);
    console.log('Width:', width, 'Height:', height);
    
  }, [minDate, maxDate, onChange, articlePositions, searchResults, isMounted, dimensions]);

      // Update only the visual styling when selection changes
  useEffect(() => {
    if (!svgRef.current || !isMounted || dimensions.width === 0) return;

    const svg = d3.select(svgRef.current);
    const circles = svg.selectAll('.article-dot')
      .data(articles);
    
    circles
    .attr('stroke', (d: Article) => {
      if (!selectedRange.start || !selectedRange.end) return 'none';
      const articleDate = new Date(d.date);
      const startDate = new Date(selectedRange.start);
      const endDate = new Date(selectedRange.end);
      return articleDate >= startDate && articleDate <= endDate ? '#1e40af' : 'none';
    })
    .attr('stroke-width', (d: Article) => {
      if (!selectedRange.start || !selectedRange.end) return 0;
      const articleDate = new Date(d.date);
      const startDate = new Date(selectedRange.start);
      const endDate = new Date(selectedRange.end);
      return articleDate >= startDate && articleDate <= endDate ? 1.5 : 0;
    })
    .attr('fill-opacity', (d: Article) => {
      if (!selectedRange.start || !selectedRange.end) return 0.3;
      const articleDate = new Date(d.date);
      const startDate = new Date(selectedRange.start);
      const endDate = new Date(selectedRange.end);
      return articleDate >= startDate && articleDate <= endDate ? 1 : 0.3;
    });

  }, [selectedRange, dimensions, isMounted, articles]);
  
  return (
    <div className="date-brush-filter w-full" ref={containerRef}>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">Filter by date</span>
        {isMounted && selectedRange.start && selectedRange.end && (
          <div className="text-sm text-gray-700">
            {formatDateDisplay(selectedRange.start)} - {formatDateDisplay(selectedRange.end)}
          </div>
        )}
      </div>
      <svg 
        ref={svgRef} 
        className="w-full" 
        style={{ minWidth: '300px' }}
      ></svg>
    </div>
  );
};

export default DateBrushFilter;