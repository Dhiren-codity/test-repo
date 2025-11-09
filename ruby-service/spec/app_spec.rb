# test/services/polyglot_api_service_test.rb
# frozen_string_literal: true

require 'minitest/autorun'
require 'rack/test'
require 'json'
require 'ostruct'
require 'time'
require_relative '../../app/app'

class PolyglotAPIServiceTest < Minitest::Test
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  def json_headers
    { 'CONTENT_TYPE' => 'application/json' }
  end

  def test_status_success_returns_health_for_all_services
    HTTParty.stub :get, ->(_url, _opts = {}) { OpenStruct.new(code: 200) } do
      get '/status'
      assert_equal 200, last_response.status
      body = JSON.parse(last_response.body)

      assert_equal 'healthy', body.dig('services', 'ruby', 'status')
      assert_equal 'healthy', body.dig('services', 'go', 'status')
      assert_equal 'healthy', body.dig('services', 'python', 'status')
    end
  end

  def test_status_unreachable_marks_service_unreachable
    # Simulate Go healthy, Python unreachable
    HTTParty.stub :get, lambda { |url, _opts = {}|
      if url.include?('8081')
        raise Timeout::Error, 'execution expired'
      else
        OpenStruct.new(code: 200)
      end
    } do
      get '/status'
      assert_equal 200, last_response.status
      body = JSON.parse(last_response.body)

      assert_equal 'healthy', body.dig('services', 'go', 'status')
      assert_equal 'unreachable', body.dig('services', 'python', 'status')
      refute_nil body.dig('services', 'python', 'error')
    end
  end

  def test_diff_success_returns_diff_and_new_review
    stub_post = lambda { |url, _opts = {}|
      if url.include?('/diff')
        OpenStruct.new(body: { diff: ['+ new line'] }.to_json)
      elsif url.include?('/review')
        OpenStruct.new(body: { score: 75.0, issues: [{ id: 1, msg: 'nit' }] }.to_json)
      else
        OpenStruct.new(body: {}.to_json)
      end
    }

    HTTParty.stub :post, stub_post do
      payload = { old_content: "a\n", new_content: "a\nb\n" }
      post '/diff', payload.to_json, json_headers

      assert_equal 200, last_response.status
      body = JSON.parse(last_response.body)

      assert body.key?('diff')
      assert body.key?('new_code_review')
      assert_equal ['+ new line'], body.dig('diff', 'diff')
      assert_equal 75.0, body.dig('new_code_review', 'score')
      assert_equal 1, body.dig('new_code_review', 'issues').length
    end
  end

  def test_diff_missing_params_returns_400
    post '/diff', { old_content: 'x' }.to_json, json_headers
    assert_equal 400, last_response.status
    body = JSON.parse(last_response.body)
    assert_equal 'Missing old_content or new_content', body['error']
  end

  def test_metrics_success_returns_overall_quality
    # overall_quality calculation:
    # review score 90 -> base 0.9
    # complexity 1 -> penalty 0.1
    # 1 issue -> penalty 0.5
    # 0.9 - 0.1 - 0.5 = 0.3 -> *100 = 30.0
    stub_post = lambda { |url, _opts = {}|
      if url.include?('8080') && url.include?('/metrics')
        OpenStruct.new(body: { complexity: 1 }.to_json)
      elsif url.include?('8081') && url.include?('/review')
        OpenStruct.new(body: { score: 90, issues: [1] }.to_json)
      else
        OpenStruct.new(body: {}.to_json)
      end
    }

    HTTParty.stub :post, stub_post do
      post '/metrics', { content: 'puts :hi' }.to_json, json_headers
      assert_equal 200, last_response.status
      body = JSON.parse(last_response.body)

      assert_equal({ 'complexity' => 1 }, body['metrics'])
      assert_equal 90, body.dig('review', 'score')
      assert_equal 30.0, body['overall_quality']
    end
  end

  def test_metrics_missing_content_returns_400
    post '/metrics', {}.to_json, json_headers
    assert_equal 400, last_response.status
    body = JSON.parse(last_response.body)
    assert_equal 'Missing content', body['error']
  end

  def test_dashboard_success_returns_summary_and_health_score
    stub_post = lambda { |url, _opts = {}|
      if url.include?('8080') && url.include?('/statistics')
        # file stats from Go service
        OpenStruct.new(body: { total_files: 2, total_lines: 100, languages: { 'ruby' => 2 } }.to_json)
      elsif url.include?('8081') && url.include?('/statistics')
        # review stats from Python service
        # health_score = 90 - (4/2)*2 - (0.5*30) = 90 - 4 - 15 = 71.0
        OpenStruct.new(body: { average_score: 90.0, total_issues: 4, average_complexity: 0.5 }.to_json)
      else
        OpenStruct.new(body: {}.to_json)
      end
    }

    fixed_time = Time.at(1_700_000_000)
    HTTParty.stub :post, stub_post do
      Time.stub :now, fixed_time do
        files = [{ path: 'a.rb', content: 'puts :a' }, { path: 'b.rb', content: 'puts :b' }]
        post '/dashboard', { files: files }.to_json, json_headers

        assert_equal 200, last_response.status
        body = JSON.parse(last_response.body)

        assert_equal fixed_time.iso8601, body['timestamp']
        assert_equal 2, body.dig('summary', 'total_files')
        assert_equal 100, body.dig('summary', 'total_lines')
        assert_equal({ 'ruby' => 2 }, body.dig('summary', 'languages'))
        assert_in_delta 90.0, body.dig('summary', 'average_quality_score'), 0.001
        assert_equal 4, body.dig('summary', 'total_issues')
        assert_in_delta 71.0, body.dig('summary', 'health_score'), 0.001
      end
    end
  end

  def test_dashboard_missing_files_returns_400
    post '/dashboard', {}.to_json, json_headers
    assert_equal 400, last_response.status
    body = JSON.parse(last_response.body)
    assert_equal 'Missing files array', body['error']
  end

  def test_detect_language_mappings
    instance = PolyglotAPI.new

    assert_equal 'ruby', instance.send(:detect_language, 'file.rb')
    assert_equal 'python', instance.send(:detect_language, 'script.PY')
    assert_equal 'go', instance.send(:detect_language, 'main.go')
    assert_equal 'javascript', instance.send(:detect_language, 'app.js')
    assert_equal 'typescript', instance.send(:detect_language, 'app.ts')
    assert_equal 'java', instance.send(:detect_language, 'App.java')
    assert_equal 'unknown', instance.send(:detect_language, 'README')
  end

  def test_calculate_quality_score_computation
    instance = PolyglotAPI.new
    metrics = { 'complexity' => 1 }
    review = { 'score' => 90, 'issues' => [1] }
    assert_in_delta 30.0, instance.send(:calculate_quality_score, metrics, review), 0.001

    # Clamping at 0
    metrics2 = { 'complexity' => 10 }
    review2 = { 'score' => 10, 'issues' => [1, 2, 3] }
    assert_in_delta 0.0, instance.send(:calculate_quality_score, metrics2, review2), 0.001

    # Clamping at 100
    metrics3 = { 'complexity' => 0 }
    review3 = { 'score' => 120, 'issues' => [] }
    assert_in_delta 100.0, instance.send(:calculate_quality_score, metrics3, review3), 0.001
  end

  def test_calculate_quality_score_returns_zero_when_error
    instance = PolyglotAPI.new
    metrics_error = { 'error' => 'oops' }
    review_ok = { 'score' => 80, 'issues' => [] }
    assert_equal 0.0, instance.send(:calculate_quality_score, metrics_error, review_ok)

    metrics_ok = { 'complexity' => 2 }
    review_error = { 'error' => 'bad' }
    assert_equal 0.0, instance.send(:calculate_quality_score, metrics_ok, review_error)
  end

  def test_calculate_dashboard_health_score_computation
    instance = PolyglotAPI.new
    file_stats = { 'total_files' => 2 }
    review_stats = { 'average_score' => 90.0, 'total_issues' => 4, 'average_complexity' => 0.5 }
    # 90 - (4/2)*2 - 0.5*30 = 90 - 4 - 15 = 71
    assert_in_delta 71.0, instance.send(:calculate_dashboard_health_score, file_stats, review_stats), 0.001
  end

  def test_calculate_dashboard_health_score_returns_zero_when_error
    instance = PolyglotAPI.new
    file_stats_error = { 'error' => 'unavailable' }
    review_stats = { 'average_score' => 90.0 }
    assert_equal 0.0, instance.send(:calculate_dashboard_health_score, file_stats_error, review_stats)

    file_stats = { 'total_files' => 1 }
    review_stats_error = { 'error' => 'bad' }
    assert_equal 0.0, instance.send(:calculate_dashboard_health_score, file_stats, review_stats_error)
  end
end