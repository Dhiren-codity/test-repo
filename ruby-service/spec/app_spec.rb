# frozen_string_literal: true

require 'minitest/autorun'
require 'ostruct'
require 'json'
require_relative '../../app/app'

class PolyglotAPIServiceTest < Minitest::Test
  def setup
    @app = PolyglotAPI.new!
  end

  # detect_language
  def test_detect_language_known_extensions
    assert_equal 'python', @app.send(:detect_language, 'foo.py')
    assert_equal 'ruby', @app.send(:detect_language, '/path/app.rb')
    assert_equal 'go', @app.send(:detect_language, 'main.go')
  end

  def test_detect_language_unknown_extension
    assert_equal 'unknown', @app.send(:detect_language, 'README')
    assert_equal 'unknown', @app.send(:detect_language, 'file.unknown')
  end

  # calculate_quality_score
  def test_calculate_quality_score_happy_path
    metrics = { 'complexity' => 3 }
    review = { 'score' => 90, 'issues' => [1] }
    result = @app.send(:calculate_quality_score, metrics, review)
    assert_in_delta 10.0, result, 0.001
  end

  def test_calculate_quality_score_with_errors_returns_zero
    assert_equal 0.0, @app.send(:calculate_quality_score, { 'error' => 'oops' }, { 'score' => 80 })
    assert_equal 0.0, @app.send(:calculate_quality_score, nil, { 'score' => 80 })
    assert_equal 0.0, @app.send(:calculate_quality_score, { 'complexity' => 1 }, { 'error' => 'oops' })
  end

  def test_calculate_quality_score_clamps_to_bounds
    high_review = { 'score' => 150, 'issues' => [] }
    no_penalty_metrics = { 'complexity' => 0 }
    assert_equal 100.0, @app.send(:calculate_quality_score, no_penalty_metrics, high_review)

    low_review = { 'score' => 0, 'issues' => [1, 2, 3] }
    high_penalty_metrics = { 'complexity' => 10 }
    assert_equal 0.0, @app.send(:calculate_quality_score, high_penalty_metrics, low_review)
  end

  # calculate_dashboard_health_score
  def test_calculate_dashboard_health_score_happy_path
    file_stats = { 'total_files' => 5 }
    review_stats = { 'average_score' => 80.0, 'total_issues' => 10, 'average_complexity' => 0.5 }
    result = @app.send(:calculate_dashboard_health_score, file_stats, review_stats)
    assert_in_delta 61.0, result, 0.001
  end

  def test_calculate_dashboard_health_score_handles_errors_and_clamps
    assert_equal 0.0, @app.send(:calculate_dashboard_health_score, { 'error' => 'x' }, { 'average_score' => 80 })

    file_stats = { 'total_files' => 5 }
    negative_result_stats = { 'average_score' => 5.0, 'total_issues' => 50, 'average_complexity' => 1.0 }
    assert_equal 0.0, @app.send(:calculate_dashboard_health_score, file_stats, negative_result_stats)

    over_max_stats = { 'average_score' => 120.0, 'total_issues' => 0, 'average_complexity' => 0 }
    assert_equal 100.0, @app.send(:calculate_dashboard_health_score, file_stats, over_max_stats)
  end

  # check_service_health
  def test_check_service_health_healthy
    HTTParty.stub :get, OpenStruct.new(code: 200) do
      result = @app.send(:check_service_health, 'http://fake-service')
      assert_equal 'healthy', result[:status]
    end
  end

  def test_check_service_health_unhealthy
    HTTParty.stub :get, OpenStruct.new(code: 500) do
      result = @app.send(:check_service_health, 'http://fake-service')
      assert_equal 'unhealthy', result[:status]
    end
  end

  def test_check_service_health_unreachable
    HTTParty.stub(:get, ->(*_args) { raise StandardError, 'boom' }) do
      result = @app.send(:check_service_health, 'http://fake-service')
      assert_equal 'unreachable', result[:status]
      assert_match 'boom', result[:error]
    end
  end

  # call_go_service
  def test_call_go_service_success
    response = OpenStruct.new(body: '{"language":"ruby","lines":["puts 1"]}')
    HTTParty.stub :post, response do
      result = @app.send(:call_go_service, '/parse', { content: 'puts 1', path: 'a.rb' })
      assert_equal({ 'language' => 'ruby', 'lines' => ['puts 1'] }, result)
    end
  end

  def test_call_go_service_failure_returns_error_hash
    HTTParty.stub(:post, ->(*_args) { raise StandardError, 'timeout' }) do
      result = @app.send(:call_go_service, '/parse', { content: 'x' })
      assert_equal 'timeout', result[:error]
    end
  end

  # call_python_service
  def test_call_python_service_success
    response = OpenStruct.new(body: '{"score":85.5,"issues":[]}')
    HTTParty.stub :post, response do
      result = @app.send(:call_python_service, '/review', { content: 'x', language: 'python' })
      assert_equal({ 'score' => 85.5, 'issues' => [] }, result)
    end
  end

  def test_call_python_service_failure_returns_error_hash
    HTTParty.stub(:post, ->(*_args) { raise StandardError, 'connection reset' }) do
      result = @app.send(:call_python_service, '/review', { content: 'x' })
      assert_equal 'connection reset', result[:error]
    end
  end
end