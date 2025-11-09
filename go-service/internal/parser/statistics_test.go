package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func makeLines(n int) []string {
	lines := make([]string, n)
	for i := 0; i < n; i++ {
		lines[i] = ""
	}
	return lines
}

func TestNewStatisticsCalculator(t *testing.T) {
	sc := NewStatisticsCalculator()
	assert.NotNil(t, sc)
}

func TestCalculateFileStats_EmptyInput(t *testing.T) {
	sc := NewStatisticsCalculator()

	stats := sc.CalculateFileStats(nil)
	require.NotNil(t, stats)

	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.NotNil(t, stats.Languages)
	assert.Len(t, stats.Languages, 0)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)

	stats = sc.CalculateFileStats([]*CodeFile{})
	require.NotNil(t, stats)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.NotNil(t, stats.Languages)
	assert.Len(t, stats.Languages, 0)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
}

func TestCalculateFileStats_SingleFile(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "file1.go",
			Size:     123,
			Lines:    makeLines(10),
			Language: "Go",
		},
	}

	stats := sc.CalculateFileStats(files)
	require.NotNil(t, stats)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 10, stats.TotalLines)
	assert.Equal(t, 123, stats.TotalSize)
	assert.Equal(t, 10.0, stats.AverageLines)
	assert.Equal(t, 123.0, stats.AverageSize)
	assert.Equal(t, "file1.go", stats.LargestFile)
	assert.Equal(t, "file1.go", stats.SmallestFile)
	require.NotNil(t, stats.Languages)
	assert.Equal(t, 1, stats.Languages["Go"])
	assert.Len(t, stats.Languages, 1)
}

func TestCalculateFileStats_MultipleFiles(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     200,
			Lines:    makeLines(2),
			Language: "Go",
		},
		{
			Path:     "b.py",
			Size:     50,
			Lines:    makeLines(10),
			Language: "Python",
		},
		{
			Path:     "c.go",
			Size:     150,
			Lines:    makeLines(4),
			Language: "Go",
		},
	}

	stats := sc.CalculateFileStats(files)
	require.NotNil(t, stats)

	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 16, stats.TotalLines) // 2 + 10 + 4
	assert.Equal(t, 400, stats.TotalSize) // 200 + 50 + 150

	// Averages with fractional results
	assert.InDelta(t, float64(16)/3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, float64(400)/3.0, stats.AverageSize, 1e-9)

	// Language counts
	require.NotNil(t, stats.Languages)
	assert.Equal(t, 2, stats.Languages["Go"])
	assert.Equal(t, 1, stats.Languages["Python"])

	// Largest and smallest by size
	assert.Equal(t, "a.go", stats.LargestFile)  // 200
	assert.Equal(t, "b.py", stats.SmallestFile) // 50
}

func TestCalculateFileStats_TiesForLargestAndSmallest(t *testing.T) {
	sc := NewStatisticsCalculator()

	// Intent: first file is initial min and max (50). Second becomes new max (100).
	// Third ties max (100) but should NOT replace second due to strict '>' check.
	// Fourth ties min (50) but should NOT replace first due to strict '<' check.
	files := []*CodeFile{
		{
			Path:     "f1.go",
			Size:     50,
			Lines:    makeLines(2),
			Language: "Go",
		},
		{
			Path:     "f2.go",
			Size:     100,
			Lines:    makeLines(4),
			Language: "Go",
		},
		{
			Path:     "f3.go",
			Size:     100,
			Lines:    makeLines(4),
			Language: "Go",
		},
		{
			Path:     "f4.py",
			Size:     50,
			Lines:    makeLines(2),
			Language: "Python",
		},
	}

	stats := sc.CalculateFileStats(files)
	require.NotNil(t, stats)

	assert.Equal(t, 4, stats.TotalFiles)
	assert.Equal(t, 12, stats.TotalLines) // 2+4+4+2
	assert.Equal(t, 300, stats.TotalSize) // 50+100+100+50
	assert.Equal(t, 3.0, stats.AverageLines)
	assert.Equal(t, 75.0, stats.AverageSize)

	// Ties should retain the first occurrence
	assert.Equal(t, "f2.go", stats.LargestFile)  // first 100
	assert.Equal(t, "f1.go", stats.SmallestFile) // first 50

	require.NotNil(t, stats.Languages)
	assert.Equal(t, 3, stats.Languages["Go"])
	assert.Equal(t, 1, stats.Languages["Python"])
}
