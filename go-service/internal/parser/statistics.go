package parser

type FileStatistics struct {
	TotalFiles   int
	TotalLines   int
	TotalSize    int
	Languages    map[string]int
	AverageLines float64
	AverageSize  float64
	LargestFile  string
	SmallestFile string
}

type StatisticsCalculator struct{}

func NewStatisticsCalculator() *StatisticsCalculator {
	return &StatisticsCalculator{}
}

func (sc *StatisticsCalculator) CalculateFileStats(files []*CodeFile) *FileStatistics {
	if len(files) == 0 {
		return &FileStatistics{
			Languages: make(map[string]int),
		}
	}

	stats := &FileStatistics{
		TotalFiles:   len(files),
		Languages:    make(map[string]int),
		LargestFile:  files[0].Path,
		SmallestFile: files[0].Path,
	}

	totalLines := 0
	totalSize := 0
	maxSize := files[0].Size
	minSize := files[0].Size

	for _, file := range files {
		totalLines += len(file.Lines)
		totalSize += file.Size
		stats.Languages[file.Language]++

		if file.Size > maxSize {
			maxSize = file.Size
			stats.LargestFile = file.Path
		}
		if file.Size < minSize {
			minSize = file.Size
			stats.SmallestFile = file.Path
		}
	}

	stats.TotalLines = totalLines
	stats.TotalSize = totalSize
	stats.AverageLines = float64(totalLines) / float64(len(files))
	stats.AverageSize = float64(totalSize) / float64(len(files))

	return stats
}
