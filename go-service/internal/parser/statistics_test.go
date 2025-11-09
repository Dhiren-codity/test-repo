package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestNewStatisticsCalculator(t *testing.T) {
	sc := NewStatisticsCalculator()
	require.NotNil(t, sc)
}

func TestCalculateFileStats_EmptyInput(t *testing.T) {
	sc := NewStatisticsCalculator()
	stats := sc.CalculateFileStats(nil)

	require.NotNil(t, stats)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.Empty(t, stats.LargestFile)
	assert.Empty(t, stats.SmallestFile)
	assert.NotNil(t, stats.Languages)
	assert.Equal(t, 0, len(stats.Languages))
	assert.InDelta(t, 0.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 0.0, stats.AverageSize, 1e-9)
}

func TestCalculateFileStats_SingleFile(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     10,
			Language: "Go",
			Lines:    []string{"line1", "line2", "line3"},
		},
	}

	stats := sc.CalculateFileStats(files)
	require.NotNil(t, stats)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 3, stats.TotalLines)
	assert.Equal(t, 10, stats.TotalSize)
	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 10.0, stats.AverageSize, 1e-9)
	assert.Equal(t, map[string]int{"Go": 1}, stats.Languages)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
}

func TestCalculateFileStats_MultipleFilesAggregations(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     10,
			Language: "Go",
			Lines:    []string{"1", "2", "3"},
		},
		{
			Path:     "b.js",
			Size:     20,
			Language: "JavaScript",
			Lines:    []string{"1", "2"},
		},
		{
			Path:     "c.py",
			Size:     5,
			Language: "Python",
			Lines:    []string{"1", "2", "3", "4"},
		},
		{
			Path:     "d.go",
			Size:     20,
			Language: "Go",
			Lines:    []string{},
		},
	}

	stats := sc.CalculateFileStats(files)
	require.NotNil(t, stats)

	assert.Equal(t, 4, stats.TotalFiles)
	assert.Equal(t, 9, stats.TotalLines)
	assert.Equal(t, 55, stats.TotalSize)
	assert.InDelta(t, 2.25, stats.AverageLines, 1e-9)
	assert.InDelta(t, 13.75, stats.AverageSize, 1e-9)

	expectedLangs := map[string]int{
		"Go":         2,
		"JavaScript": 1,
		"Python":     1,
	}
	assert.Equal(t, expectedLangs, stats.Languages)

	// Largest is the first 20-size file (b.js), not the second (d.go)
	assert.Equal(t, "b.js", stats.LargestFile)
	// Smallest is c.py (size 5)
	assert.Equal(t, "c.py", stats.SmallestFile)
}

func TestCalculateFileStats_TieSizesKeepsFirst(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "x.txt",
			Size:     100,
			Language: "Text",
			Lines:    []string{"line"},
		},
		{
			Path:     "y.txt",
			Size:     100,
			Language: "Text",
			Lines:    []string{"line1", "line2"},
		},
	}

	stats := sc.CalculateFileStats(files)
	require.NotNil(t, stats)

	// When sizes tie, both largest and smallest should remain the first file encountered
	assert.Equal(t, "x.txt", stats.LargestFile)
	assert.Equal(t, "x.txt", stats.SmallestFile)
}

func TestCalculateFileStats_ZeroSizeAndZeroLines(t *testing.T) {
	sc := NewStatisticsCalculator()
	files := []*CodeFile{
		{
			Path:     "a.bin",
			Size:     10,
			Language: "",
			Lines:    []string{"a", "b"},
		},
		{
			Path:     "b.bin",
			Size:     0,
			Language: "",
			Lines:    []string{}, // zero lines
		},
		{
			Path:     "c.bin",
			Size:     5,
			Language: "",
			Lines:    []string{"x", "y", "z"},
		},
	}

	stats := sc.CalculateFileStats(files)
	require.NotNil(t, stats)

	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 5, stats.TotalLines)
	assert.Equal(t, 15, stats.TotalSize)
	assert.InDelta(t, 5.0/3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 5.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "a.bin", stats.LargestFile)
	assert.Equal(t, "b.bin", stats.SmallestFile)

	// Verify that empty language key is counted
	assert.Equal(t, map[string]int{"": 3}, stats.Languages)
}
