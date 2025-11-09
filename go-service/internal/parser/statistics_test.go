package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestNewStatisticsCalculator(t *testing.T) {
	calc := NewStatisticsCalculator()
	assert.NotNil(t, calc)
}

func TestStatisticsCalculator_CalculateFileStats_Empty(t *testing.T) {
	calc := NewStatisticsCalculator()

	stats := calc.CalculateFileStats(nil)
	assert.NotNil(t, stats)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, stats.TotalLines)
	assert.Equal(t, 0, stats.TotalSize)
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
	assert.NotNil(t, stats.Languages)
	assert.Len(t, stats.Languages, 0)
	assert.Equal(t, 0.0, stats.AverageLines)
	assert.Equal(t, 0.0, stats.AverageSize)

	stats2 := calc.CalculateFileStats([]*CodeFile{})
	assert.NotNil(t, stats2)
	assert.Equal(t, 0, stats2.TotalFiles)
	assert.Equal(t, 0, stats2.TotalLines)
	assert.Equal(t, 0, stats2.TotalSize)
	assert.Equal(t, "", stats2.LargestFile)
	assert.Equal(t, "", stats2.SmallestFile)
	assert.NotNil(t, stats2.Languages)
	assert.Len(t, stats2.Languages, 0)
	assert.Equal(t, 0.0, stats2.AverageLines)
	assert.Equal(t, 0.0, stats2.AverageSize)
}

func TestStatisticsCalculator_CalculateFileStats_SingleFile(t *testing.T) {
	calc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.go",
			Language: "Go",
			Size:     123,
			Lines:    []string{"l1", "l2", "l3"},
		},
	}

	stats := calc.CalculateFileStats(files)

	assert.Equal(t, 1, stats.TotalFiles)
	assert.Equal(t, 3, stats.TotalLines)
	assert.Equal(t, 123, stats.TotalSize)
	assert.Equal(t, "a.go", stats.LargestFile)
	assert.Equal(t, "a.go", stats.SmallestFile)
	assert.InDelta(t, 3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 123.0, stats.AverageSize, 1e-9)

	assert.Len(t, stats.Languages, 1)
	assert.Equal(t, 1, stats.Languages["Go"])
}

func TestStatisticsCalculator_CalculateFileStats_MultipleFiles(t *testing.T) {
	calc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.go",
			Language: "Go",
			Size:     100,
			Lines:    make([]string, 10),
		},
		{
			Path:     "b.py",
			Language: "Python",
			Size:     50,
			Lines:    make([]string, 5),
		},
		{
			Path:     "c.go",
			Language: "Go",
			Size:     150,
			Lines:    make([]string, 20),
		},
	}

	stats := calc.CalculateFileStats(files)

	assert.Equal(t, 3, stats.TotalFiles)
	assert.Equal(t, 35, stats.TotalLines)
	assert.Equal(t, 300, stats.TotalSize)
	assert.Equal(t, "c.go", stats.LargestFile)
	assert.Equal(t, "b.py", stats.SmallestFile)
	assert.InDelta(t, float64(35)/3.0, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)

	assert.Len(t, stats.Languages, 2)
	assert.Equal(t, 2, stats.Languages["Go"])
	assert.Equal(t, 1, stats.Languages["Python"])
}

func TestStatisticsCalculator_CalculateFileStats_TieSizesPreferFirst(t *testing.T) {
	calc := NewStatisticsCalculator()

	files := []*CodeFile{
		{
			Path:     "a.js",
			Language: "JavaScript",
			Size:     100,
			Lines:    make([]string, 1),
		},
		{
			Path:     "b.js",
			Language: "JavaScript",
			Size:     100,
			Lines:    make([]string, 2),
		},
	}

	stats := calc.CalculateFileStats(files)

	// With equal sizes, LargestFile and SmallestFile remain as the first file
	assert.Equal(t, "a.js", stats.LargestFile)
	assert.Equal(t, "a.js", stats.SmallestFile)
	assert.Equal(t, 2, stats.TotalFiles)
	assert.Equal(t, 3, stats.TotalLines)
	assert.Equal(t, 200, stats.TotalSize)
	assert.InDelta(t, 1.5, stats.AverageLines, 1e-9)
	assert.InDelta(t, 100.0, stats.AverageSize, 1e-9)

	assert.Len(t, stats.Languages, 1)
	assert.Equal(t, 2, stats.Languages["JavaScript"])
}

func TestStatisticsCalculator_CalculateFileStats_NilReceiver(t *testing.T) {
	var calc *StatisticsCalculator // nil receiver
	stats := calc.CalculateFileStats(nil)

	assert.NotNil(t, stats)
	assert.NotNil(t, stats.Languages)
	assert.Equal(t, 0, stats.TotalFiles)
	assert.Equal(t, 0, len(stats.Languages))
	assert.Equal(t, "", stats.LargestFile)
	assert.Equal(t, "", stats.SmallestFile)
}
