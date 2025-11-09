# frozen_string_literal: true

require 'minitest/autorun'
require 'rack/test'
require 'json'
require 'time'
require_relative '../../app/app'

class PolyglotAPIServiceTest < Minitest::Test
  include Rack::Test::Methods

  class FakeResponse
    attr_reader :code, :body

    def initialize(code: 200, body: '{}')
      @code = code
      @body = body
    end
  end

  def app
    PolyglotAPI
  end

  # New tests only (do not duplicate existing RSpec tests)

  def test_status_reports_health_and_unhealthy
    HTTParty.stub(:get, ->(url, **_kwargs) do
      if url.include?('8080/health')
        FakeResponse.new(code: 200, body: '{}')
      else
        FakeResponse.new(code: 500, body: '{}')
      end
    end) do
      get '/status'
      assert last_response.ok?
      data = JSON.parse(last_response.body)
      assert_equal 'healthy', data['services']['go']['status']
      assert_equal 'unhealthy', data['services']['python']['status']
      assert_equal 'healthy', data['services']['ruby']['status']
    end
  end

  def test_analyze_missing_content_returns_400
    post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    data = JSON.parse(last_response.body)
    assert_equal 'Missing content', data['error']
  end

  def test_diff_success_returns_diff_and_review
    HTTParty.stub(:post, ->(url, **_kwargs) do
      if url.include?('8080/diff')
        FakeResponse.new(body: { diff: '--- a\n+++ b\n' }.to_json)
      elsif url.include?('8081/review')
        FakeResponse.new(body: { score: 92, issues: [] }.to_json)
      else
        FakeResponse.new(body: '{}')
      end
    end) do
      payload = { old_content: "a = 1\n", new_content: "a = 2\n" }
      post '/diff', payload.to_json, 'CONTENT_TYPE' => 'application/json'
      assert last_response.ok?
      data = JSON.parse(last_response.body)
      assert_includes data.keys, 'diff'
      assert_includes data.keys, 'new_code_review'
      assert_equal 92, data['new_code_review']['score']
    end
  end

  def test_diff_missing_params_returns_400
    post '/diff', { new_content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    data = JSON.parse(last_response.body)
    assert_equal 'Missing old_content or new_content', data['error']
  end

  def test_metrics_success_and_overall_quality_computation
    HTTParty.stub(:post, ->(url, **_kwargs) do
      if url.include?('8080/metrics')
        FakeResponse.new(body: { complexity: 1 }.to_json)
      elsif url.include?('8081/review')
        FakeResponse.new(body: { score: 90, issues: [{}] }.to_json)
      else
        FakeResponse.new(body: '{}')
      end
    end) do
      post '/metrics', { content: 'def x(): pass' }.to_json, 'CONTENT_TYPE' => 'application/json'
      assert last_response.ok?
      data = JSON.parse(last_response.body)
      # base_score = 0.9, complexity_penalty = 0.1, issue_penalty = 0.5 => final 0.3 => 30.0
      assert_in_delta 30.0, data['overall_quality'], 0.001
      assert_equal 90, data['review']['score']
      assert_equal 1, data['metrics']['complexity']
    end
  end

  def test_dashboard_success_and_health_score_calculation
    HTTParty.stub(:post, ->(url, **_kwargs) do
      if url.include?('8080/statistics')
        FakeResponse.new(body: { total_files: 5, total_lines: 1000, languages: { 'ruby' => 3 } }.to_json)
      elsif url.include?('8081/statistics')
        FakeResponse.new(body: { average_score: 85.0, total_issues: 10, average_complexity: 0.5 }.to_json)
      else
        FakeResponse.new(body: '{}')
      end
    end) do
      files = [{ path: 'a.rb', content: 'puts 1' }, { path: 'b.py', content: 'print(1)' }]
      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      assert last_response.ok?
      data = JSON.parse(last_response.body)
      assert data['timestamp'].is_a?(String)
      summary = data['summary']
      assert_equal 5, summary['total_files']
      assert_equal 1000, summary['total_lines']
      assert_equal({ 'ruby' => 3 }, summary['languages'])
      # health_score = 85 - (10/5)*2 - 0.5*30 = 85 - 4 - 15 = 66
      assert_in_delta 66.0, summary['health_score'], 0.001
      assert_in_delta 85.0, summary['average_quality_score'], 0.001
    end
  end

  def test_dashboard_missing_files_returns_400
    post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
    assert_equal 400, last_response.status
    data = JSON.parse(last_response.body)
    assert_equal 'Missing files array', data['error']
  end

  # Unit tests for private helper methods (service logic)

  def test_detect_language_mappings
    instance = PolyglotAPI.allocate
    assert_equal 'ruby', instance.send(:detect_language, 'foo.rb')
    assert_equal 'python', instance.send(:detect_language, 'bar.PY')
    assert_equal 'go', instance.send(:detect_language, 'main.go')
    assert_equal 'javascript', instance.send(:detect_language, 'x.js')
    assert_equal 'unknown', instance.send(:detect_language, 'README')
  end

  def test_calculate_quality_score_clamps_and_computes
    instance = PolyglotAPI.allocate
    # Negative final score should clamp to 0
    metrics = { 'complexity' => 5 }
    review = { 'score' => 50, 'issues' => [{}, {}] }
    assert_equal 0.0, instance.send(:calculate_quality_score, metrics, review)

    # Positive computed score
    metrics2 = { 'complexity' => 1 }
    review2 = { 'score' => 90, 'issues' => [{}] }
    # 90/100 - 0.1 - 0.5 = 0.3 => 30.0
    assert_in_delta 30.0, instance.send(:calculate_quality_score, metrics2, review2), 0.001

    # Error presence yields 0.0
    metrics_err = { 'error' => 'fail' }
    review_ok = { 'score' => 90, 'issues' => [] }
    assert_equal 0.0, instance.send(:calculate_quality_score, metrics_err, review_ok)
  end

  def test_calculate_dashboard_health_score_and_clamp
    instance = PolyglotAPI.allocate

    # Normal case
    file_stats = { 'total_files' => 10 }
    review_stats = { 'average_score' => 80.0, 'total_issues' => 10, 'average_complexity' => 0.3 }
    # 80 - (10/10)*2 - 0.3*30 = 80 - 2 - 9 = 69
    assert_in_delta 69.0, instance.send(:calculate_dashboard_health_score, file_stats, review_stats), 0.001

    # Negative clamp to 0
    file_stats2 = { 'total_files' => 2 }
    review_stats2 = { 'average_score' => 10.0, 'total_issues' => 100, 'average_complexity' => 0.0 }
    assert_equal 0.0, instance.send(:calculate_dashboard_health_score, file_stats2, review_stats2)

    # Error presence yields 0.0
    assert_equal 0.0, instance.send(:calculate_dashboard_health_score, { 'error' => 'x' }, review_stats)
  end

  def test_check_service_health_success_and_unreachable
    instance = PolyglotAPI.allocate

    # Success 200
    HTTParty.stub(:get, ->(_url, **_kwargs) { FakeResponse.new(code: 200, body: '{}') }) do
      res = instance.send(:check_service_health, 'http://example.test')
      assert_equal 'healthy', res[:status]
    end

    # Unreachable error
    HTTParty.stub(:get, ->(_url, **_kwargs) { raise StandardError, 'timeout' }) do
      res = instance.send(:check_service_health, 'http://example.test')
      assert_equal 'unreachable', res[:status]
      assert_match(/timeout/, res[:error])
    end
  end

  def test_call_go_service_success_and_error
    instance = PolyglotAPI.allocate

    # Success
    HTTParty.stub(:post, ->(_url, **_kwargs) { FakeResponse.new(body: { ok: true }.to_json) }) do
      result = instance.send(:call_go_service, '/metrics', { content: 'x' })
      assert_equal true, result['ok']
    end

    # Error rescue path returns symbol key :error
    HTTParty.stub(:post, ->(_url, **_kwargs) { raise StandardError, 'boom' }) do
      result = instance.send(:call_go_service, '/metrics', { content: 'x' })
      assert result[:error]
      assert_match(/boom/, result[:error])
    end
  end

  def test_call_python_service_success_and_error
    instance = PolyglotAPI.allocate

    HTTParty.stub(:post, ->(_url, **_kwargs) { FakeResponse.new(body: { score: 99 }.to_json) }) do
      result = instance.send(:call_python_service, '/review', { content: 'x' })
      assert_equal 99, result['score']
    end

    HTTParty.stub(:post, ->(_url, **_kwargs) { raise StandardError, 'py-fail' }) do
      result = instance.send(:call_python_service, '/review', { content: 'x' })
      assert result[:error]
      assert_match(/py-fail/, result[:error])
    end
  end
end