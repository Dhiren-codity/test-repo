package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func makeLines(n int) []string {
	lines := make([]string, n)
	for i := 0; i < n; i++ {
		lines[i] = "line"
	}
	return lines
}

func TestNewStatisticsCalculator_ReturnsNonNil(t *testing.T) {
	sc := NewStatisticsCalculator()
	require.NotNil(t, sc)
}

func TestStatisticsCalculator_CalculateFileStats_EmptyInput(t *testing.T) {
	sc := NewStatisticsCalculator()
	stats := sc.CalculateFileStats(nil)

	require.NotNil(t, stats)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
	require.NotNil(t, stats.Languages)
	assert.Len(t, stats.Languages, 0)

	stats = sc.CalculateFileStats([]*CodeFile{})
	require.NotNil(t, stats)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
	require.NotNil(t, stats.Languages)
	assert.Len(t, stats.Languages, 0)
}

func TestStatisticsCalculator_CalculateFileStats_SingleFile(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     100,
			Lines:    makeLines(10),
			Language: "Go",
		},
	}

	stats := sc.CalculateFileStats(files)
	require.NotNil(t, stats)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 10, stats.TotalLines)
	assert.Equal(t, 100, stats.TotalSize)
	assert.InDelta(t, 10.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)

	require.NotNil(t, stats.Languages)
	assert.Equal(t, 1, stats.Languages["Go"])
	assert.Len(t, stats.Languages, 1)
}

func TestStatisticsCalculator_CalculateFileStats_MultipleFiles_Mixed(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.go",
			Size:     200,
			Lines:    makeLines(5),
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
			Size:     300,
			Lines:    makeLines(0),
			Language: "Go",
		},
		{
			Path:     "d.py",
			Size:     50,
			Lines:    makeLines(3),
			Language: "Python",
		},
		{
			Path:     "e.go",
			Size:     300,
			Lines:    makeLines(8),
			Language: "Go",
		},
	}

	stats := sc.CalculateFileStats(files)
	require.NotNil(t, stats)

	assert.Equal(t, 5, stats.TotalFiles)
	assert.Equal(t, 26, stats.TotalLines)
	assert.Equal(t, 900, stats.TotalSize)
	assert.InDelta(t, 5.2, stats.AverageLines, 1e-9)
	assert.InDelta(t, 180.0, stats.AverageSize, 1e-9)

	// Largest should remain the first file that reached max (c.go),
	// even though e.go ties in size.
	assert.Equal(t, "c.go", stats.LargestFile)
	// Smallest should remain the first 50-sized file (b.py)
	assert.Equal(t, "b.py", stats.SmallestFile)

	require.NotNil(t, stats.Languages)
	assert.Equal(t, 3, stats.Languages["Go"])
	assert.Equal(t, 2, stats.Languages["Python"])
	assert.Len(t, stats.Languages, 2)
}

func TestStatisticsCalculator_CalculateFileStats_SizeTieBehavior(t *testing.T) {
	sc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "first.txt",
			Size:     100,
			Lines:    makeLines(2),
			Language: "",
		},
		{
			Path:     "second.txt",
			Size:     100,
			Lines:    makeLines(3),
			Language: "",
		},
	}

	stats := sc.CalculateFileStats(files)
	require.NotNil(t, stats)

	// On tie, LargestFile and SmallestFile should stay as the first encounter
	assert.Equal(t, "first.txt", stats.LargestFile)
	assert.Equal(t, "first.txt", stats.SmallestFile)

	assert.Equal(t, 2, stats.TotalFiles)
	assert.Equal(t, 5, stats.TotalLines)
	assert.Equal(t, 200, stats.TotalSize)
	assert.InDelta(t, 2.5, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)

	// Empty language key increments properly
	require.NotNil(t, stats.Languages)
	assert.Equal(t, 2, stats.Languages[""])
	assert.Len(t, stats.Languages, 1)
}
