# test/services/polyglot_api_service_test.rb
# frozen_string_literal: true

require 'minitest/autorun'
require 'json'
require_relative '../../app/app'

class PolyglotAPIServiceTest < Minitest::Test
  def setup
    @service = PolyglotAPI.new
  end

  # detect_language

  def test_detect_language_known_extensions
    assert_equal 'go', @service.send(:detect_language, 'main.go')
    assert_equal 'python', @service.send(:detect_language, 'script.py')
    assert_equal 'ruby', @service.send(:detect_language, 'app.rb')
    assert_equal 'javascript', @service.send(:detect_language, 'index.js')
    assert_equal 'typescript', @service.send(:detect_language, 'types.ts')
    assert_equal 'java', @service.send(:detect_language, 'Main.java')
  end

  def test_detect_language_case_insensitive_and_unknown
    assert_equal 'javascript', @service.send(:detect_language, '/path/FILE.JS')
    assert_equal 'unknown', @service.send(:detect_language, 'Makefile')
    assert_equal 'unknown', @service.send(:detect_language, 'README.md')
  end

  # calculate_quality_score

  def test_calculate_quality_score_success_with_penalties_and_clamp_low
    metrics = { 'complexity' => 10 }
    review = { 'score' => 80, 'issues' => [{}, {}] }
    # base_score = 0.8, complexity_penalty = 1.0, issue_penalty = 1.0 -> final -1.2 => 0 after clamp
    assert_equal 0, @service.send(:calculate_quality_score, metrics, review)
  end

  def test_calculate_quality_score_success_with_rounding
    metrics = { 'complexity' => 1 }
    review = { 'score' => 90, 'issues' => [{}] }
    # base 0.9 - (0.1 + 0.5) = 0.3 => 30.0
    assert_in_delta 30.0, @service.send(:calculate_quality_score, metrics, review), 0.001
  end

  def test_calculate_quality_score_clamps_high
    metrics = { 'complexity' => 0 }
    review = { 'score' => 120, 'issues' => [] }
    assert_equal 100, @service.send(:calculate_quality_score, metrics, review)
  end

  def test_calculate_quality_score_handles_errors
    metrics_error = { 'error' => 'boom' }
    review_ok = { 'score' => 100, 'issues' => [] }
    review_error = { 'error' => 'nope' }
    metrics_ok = { 'complexity' => 0 }

    assert_equal 0.0, @service.send(:calculate_quality_score, metrics_error, review_ok)
    assert_equal 0.0, @service.send(:calculate_quality_score, metrics_ok, review_error)
    assert_equal 0.0, @service.send(:calculate_quality_score, nil, review_ok)
    assert_equal 0.0, @service.send(:calculate_quality_score, metrics_ok, nil)
  end

  # calculate_dashboard_health_score

  def test_calculate_dashboard_health_score_success
    file_stats = { 'total_files' => 5 }
    review_stats = { 'average_score' => 85.0, 'total_issues' => 10, 'average_complexity' => 0.5 }
    # issue_penalty = (10/5)*2 = 4, complexity_penalty = 0.5*30 = 15
    # 85 - 19 = 66.0
    assert_in_delta 66.0, @service.send(:calculate_dashboard_health_score, file_stats, review_stats), 0.001
  end

  def test_calculate_dashboard_health_score_clamps_and_defaults
    file_stats = { 'total_files' => nil } # defaults to 1
    review_stats = { 'average_score' => 120.0, 'total_issues' => 0, 'average_complexity' => 0.0 }
    assert_equal 100.0, @service.send(:calculate_dashboard_health_score, file_stats, review_stats)

    file_stats_bad = { 'error' => 'down' }
    review_stats_ok = { 'average_score' => 90.0, 'total_issues' => 0, 'average_complexity' => 0.0 }
    assert_equal 0.0, @service.send(:calculate_dashboard_health_score, file_stats_bad, review_stats_ok)

    file_stats_ok = { 'total_files' => 2 }
    review_stats_bad = { 'error' => 'oops' }
    assert_equal 0.0, @service.send(:calculate_dashboard_health_score, file_stats_ok, review_stats_bad)

    # Negative health clamps to 0
    file_stats2 = { 'total_files' => 1 }
    review_stats2 = { 'average_score' => 10.0, 'total_issues' => 20, 'average_complexity' => 1.0 }
    assert_equal 0.0, @service.send(:calculate_dashboard_health_score, file_stats2, review_stats2)
  end

  # check_service_health

  def test_check_service_health_healthy
    fake_resp = Struct.new(:code).new(200)
    HTTParty.stub(:get, ->(_url, **_kwargs) { fake_resp }) do
      result = @service.send(:check_service_health, 'http://example.com')
      assert_equal 'healthy', result[:status]
    end
  end

  def test_check_service_health_unhealthy
    fake_resp = Struct.new(:code).new(500)
    HTTParty.stub(:get, ->(_url, **_kwargs) { fake_resp }) do
      result = @service.send(:check_service_health, 'http://example.com')
      assert_equal 'unhealthy', result[:status]
    end
  end

  def test_check_service_health_unreachable
    HTTParty.stub(:get, ->(_url, **_kwargs) { raise StandardError, 'boom' }) do
      result = @service.send(:check_service_health, 'http://example.com')
      assert_equal 'unreachable', result[:status]
      assert_includes result[:error], 'boom'
    end
  end

  # call_go_service

  def test_call_go_service_success
    response = Struct.new(:body).new({ 'ok' => true, 'service' => 'go' }.to_json)
    HTTParty.stub(:post, ->(_url, **_kwargs) { response }) do
      result = @service.send(:call_go_service, '/metrics', { content: 'code' })
      assert_equal true, result['ok']
      assert_equal 'go', result['service']
    end
  end

  def test_call_go_service_error
    HTTParty.stub(:post, ->(_url, **_kwargs) { raise Timeout::Error, 'timeout' }) do
      result = @service.send(:call_go_service, '/metrics', { content: 'code' })
      assert_includes result[:error], 'timeout'
    end
  end

  # call_python_service

  def test_call_python_service_success
    response = Struct.new(:body).new({ 'ok' => true, 'service' => 'python' }.to_json)
    HTTParty.stub(:post, ->(_url, **_kwargs) { response }) do
      result = @service.send(:call_python_service, '/review', { content: 'code' })
      assert_equal true, result['ok']
      assert_equal 'python', result['service']
    end
  end

  def test_call_python_service_error
    HTTParty.stub(:post, ->(_url, **_kwargs) { raise StandardError, 'connection refused' }) do
      result = @service.send(:call_python_service, '/review', { content: 'code' })
      assert_includes result[:error], 'connection refused'
    end
  end
end