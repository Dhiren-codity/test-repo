package parser

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func cf(path string, size int, lang string, lines int) *CodeFile {
	ls := make([]string, lines)
	for i := 0; i < lines; i++ {
		ls[i] = "line"
	}
	return &CodeFile{
		Path:     path,
		Size:     size,
		Language: lang,
		Lines:    ls,
	}
}

func TestNewStatisticsCalculator_NotNil(t *testing.T) {
	sc := NewStatisticsCalculator()
	require.NotNil(t, sc)
}

func TestStatisticsCalculator_CalculateFileStats(t *testing.T) {
	tests := []struct {
		name     string
		files    []*CodeFile
		expected FileStatistics
	}{
		{
			name:  "empty input",
			files: nil,
			expected: FileStatistics{
				TotalFiles:   0,
				TotalLines:   0,
				TotalSize:    0,
				Languages:    map[string]int{},
				AverageLines: 0,
				AverageSize:  0,
				LargestFile:  "",
				SmallestFile: "",
			},
		},
		{
			name: "single file",
			files: []*CodeFile{
				cf("file.go", 120, "Go", 3),
			},
			expected: FileStatistics{
				TotalFiles:   1,
				TotalLines:   3,
				TotalSize:    120,
				Languages:    map[string]int{"Go": 1},
				AverageLines: 3.0,
				AverageSize:  120.0,
				LargestFile:  "file.go",
				SmallestFile: "file.go",
			},
		},
		{
			name: "multiple files with ties for largest and smallest",
			files: []*CodeFile{
				cf("a.go", 100, "Go", 10),
				cf("b.js", 50, "JS", 5),
				cf("c.go", 200, "Go", 20),
				cf("d.py", 200, "Python", 30),
				cf("e.js", 50, "JS", 0),
			},
			expected: FileStatistics{
				TotalFiles:   5,
				TotalLines:   65,
				TotalSize:    600,
				Languages:    map[string]int{"Go": 2, "JS": 2, "Python": 1},
				AverageLines: 13.0,
				AverageSize:  120.0,
				LargestFile:  "c.go", // first 200
				SmallestFile: "b.js", // first 50
			},
		},
		{
			name: "all files same size ensures first is both largest and smallest",
			files: []*CodeFile{
				cf("first.txt", 42, "", 1),
				cf("second.txt", 42, "", 2),
				cf("third.txt", 42, "", 3),
			},
			expected: FileStatistics{
				TotalFiles:   3,
				TotalLines:   6,
				TotalSize:    126,
				Languages:    map[string]int{"": 3},
				AverageLines: 2.0,
				AverageSize:  42.0,
				LargestFile:  "first.txt",
				SmallestFile: "first.txt",
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sc := NewStatisticsCalculator()
			got := sc.CalculateFileStats(tt.files)

			require.NotNil(t, got)
			require.NotNil(t, got.Languages)

			assert.Equal(t, tt.expected.TotalFiles, got.TotalFiles)
			assert.Equal(t, tt.expected.TotalLines, got.TotalLines)
			assert.Equal(t, tt.expected.TotalSize, got.TotalSize)
			assert.Equal(t, tt.expected.Languages, got.Languages)
			assert.InDelta(t, tt.expected.AverageLines, got.AverageLines, 1e-9)
			assert.InDelta(t, tt.expected.AverageSize, got.AverageSize, 1e-9)
			assert.Equal(t, tt.expected.LargestFile, got.LargestFile)
			assert.Equal(t, tt.expected.SmallestFile, got.SmallestFile)
		})
	}
}
