# test/services/polyglot_api_service_test.rb
# frozen_string_literal: true

require 'minitest/autorun'
require 'json'
require_relative '../../app/app'

class PolyglotAPIServiceTest < Minitest::Test
  Response = Struct.new(:body, :code)

  def setup
    @app = PolyglotAPI.new
  end

  # Private helper: detect_language
  def test_detect_language_mappings
    assert_equal 'python', @app.send(:detect_language, 'test.py')
    assert_equal 'ruby', @app.send(:detect_language, 'script.rb')
    assert_equal 'javascript', @app.send(:detect_language, 'index.js')
    assert_equal 'typescript', @app.send(:detect_language, 'app.ts')
    assert_equal 'go', @app.send(:detect_language, 'main.go')
    assert_equal 'java', @app.send(:detect_language, 'Main.java')
    assert_equal 'unknown', @app.send(:detect_language, 'README.txt')
    assert_equal 'unknown', @app.send(:detect_language, 'no_extension')
  end

  # Private helper: calculate_quality_score
  def test_calculate_quality_score_perfect
    metrics = { 'complexity' => 0 }
    review = { 'score' => 100, 'issues' => [] }
    score = @app.send(:calculate_quality_score, metrics, review)
    assert_equal 100, score
  end

  def test_calculate_quality_score_with_penalties_and_clamp_to_zero
    metrics = { 'complexity' => 5 }
    review = { 'score' => 80, 'issues' => [1, 2] }
    # base_score = 0.8; complexity_penalty = 0.5; issue_penalty = 1.0 => final negative => clamp to 0
    score = @app.send(:calculate_quality_score, metrics, review)
    assert_equal 0, score
  end

  def test_calculate_quality_score_returns_zero_when_error_present
    metrics = { 'error' => 'timeout' }
    review = { 'score' => 90, 'issues' => [] }
    assert_equal 0.0, @app.send(:calculate_quality_score, metrics, review)

    metrics = { 'complexity' => 1 }
    review = { 'error' => 'unavailable' }
    assert_equal 0.0, @app.send(:calculate_quality_score, metrics, review)

    assert_equal 0.0, @app.send(:calculate_quality_score, nil, review)
    assert_equal 0.0, @app.send(:calculate_quality_score, metrics, nil)
  end

  # Private helper: calculate_dashboard_health_score
  def test_calculate_dashboard_health_score_typical
    file_stats = { 'total_files' => 10 }
    review_stats = { 'average_score' => 90, 'total_issues' => 5, 'average_complexity' => 0.5 }
    # issue_penalty = (5/10)*2 = 1.0; complexity_penalty = 0.5*30 = 15 => 90-1-15 = 74
    health = @app.send(:calculate_dashboard_health_score, file_stats, review_stats)
    assert_equal 74.0, health
  end

  def test_calculate_dashboard_health_score_clamps_bounds
    # Clamp to 0
    file_stats = { 'total_files' => 2 }
    review_stats = { 'average_score' => 10, 'total_issues' => 10, 'average_complexity' => 1.0 }
    health = @app.send(:calculate_dashboard_health_score, file_stats, review_stats)
    assert_equal 0.0, health

    # Clamp to 100
    file_stats = { 'total_files' => 1 }
    review_stats = { 'average_score' => 120, 'total_issues' => 0, 'average_complexity' => 0.0 }
    health = @app.send(:calculate_dashboard_health_score, file_stats, review_stats)
    assert_equal 100.0, health
  end

  def test_calculate_dashboard_health_score_returns_zero_when_error_present
    file_stats = { 'error' => 'bad' }
    review_stats = { 'average_score' => 80 }
    assert_equal 0.0, @app.send(:calculate_dashboard_health_score, file_stats, review_stats)

    file_stats = { 'total_files' => 3 }
    review_stats = { 'error' => 'unavailable' }
    assert_equal 0.0, @app.send(:calculate_dashboard_health_score, file_stats, review_stats)

    assert_equal 0.0, @app.send(:calculate_dashboard_health_score, nil, review_stats)
    assert_equal 0.0, @app.send(:calculate_dashboard_health_score, file_stats, nil)
  end

  # Private helper: check_service_health (stubs HTTParty.get)
  def test_check_service_health_healthy_when_code_200
    HTTParty.stub :get, Response.new('', 200) do
      result = @app.send(:check_service_health, 'http://example.com')
      assert_equal 'healthy', result[:status]
      assert_nil result[:error]
    end
  end

  def test_check_service_health_unhealthy_when_non_200
    HTTParty.stub :get, Response.new('', 500) do
      result = @app.send(:check_service_health, 'http://example.com')
      assert_equal 'unhealthy', result[:status]
      assert_nil result[:error]
    end
  end

  def test_check_service_health_unreachable_on_exception
    def failing_get(*)
      raise Timeout::Error, 'execution expired'
    end

    HTTParty.stub :get, method(:failing_get) do
      result = @app.send(:check_service_health, 'http://example.com')
      assert_equal 'unreachable', result[:status]
      assert_match(/execution expired/, result[:error])
    end
  end

  # Private helper: call_go_service (stubs HTTParty.post)
  def test_call_go_service_success_parses_json
    payload = { language: 'ruby', lines: %w[a b] }
    response = Response.new(payload.to_json, 200)
    HTTParty.stub :post, response do
      result = @app.send(:call_go_service, '/parse', { content: 'puts 1' })
      assert_equal 'ruby', result['language']
      assert_equal %w[a b], result['lines']
    end
  end

  def test_call_go_service_returns_error_on_exception
    def failing_post(*)
      raise StandardError, 'connection refused'
    end

    HTTParty.stub :post, method(:failing_post) do
      result = @app.send(:call_go_service, '/parse', { content: 'puts 1' })
      assert_match(/connection refused/, result[:error] || result['error'])
    end
  end

  # Private helper: call_python_service (stubs HTTParty.post)
  def test_call_python_service_success_parses_json
    payload = { score: 88.5, issues: [] }
    response = Response.new(payload.to_json, 200)
    HTTParty.stub :post, response do
      result = @app.send(:call_python_service, '/review', { content: 'print(1)' })
      assert_in_delta 88.5, result['score']
      assert_equal [], result['issues']
    end
  end

  def test_call_python_service_returns_error_on_exception
    def failing_post_py(*)
      raise StandardError, 'timeout'
    end

    HTTParty.stub :post, method(:failing_post_py) do
      result = @app.send(:call_python_service, '/review', { content: 'print(1)' })
      assert_match(/timeout/, result[:error] || result['error'])
    end
  end
end