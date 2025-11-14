# frozen_string_literal: true

require_relative 'spec_helper'
require_relative '../app/app'

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  describe 'GET /health' do
    it 'returns healthy status' do
      get '/health'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('healthy')
    end
  end

  describe 'POST /analyze' do
    it 'accepts valid content' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'python', 'lines' => ['def test'] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 85.0, 'issues' => [] })

      post '/analyze', { content: 'def test(): pass', path: 'test.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response).to have_key('summary')
    end
  end

  describe 'GET /status' do
    context 'when dependent services are healthy' do
      it 'reports healthy for go and python' do
        allow(HTTParty).to receive(:get).and_return(double(code: 200))
        get '/status'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['services']['ruby']['status']).to eq('healthy')
        expect(json_response['services']['go']['status']).to eq('healthy')
        expect(json_response['services']['python']['status']).to eq('healthy')
      end
    end

    context 'when a service is unreachable' do
      it 'reports unreachable with error' do
        allow(HTTParty).to receive(:get) do |url, _opts|
          raise StandardError, 'timeout' if url.start_with?(app.settings.python_service_url)

          double(code: 200)
        end
        get '/status'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['services']['go']['status']).to eq('healthy')
        expect(json_response['services']['python']['status']).to eq('unreachable')
        expect(json_response['services']['python']['error']).to include('timeout')
      end
    end
  end

  describe 'POST /analyze' do
    context 'when validation fails' do
      it 'returns 422 with validation details and does not call services' do
        allow(RequestValidator).to receive(:validate_analyze_request).and_return([double(to_hash: { field: 'content',
                                                                                                    message: 'missing' })])
        allow(RequestValidator).to receive(:sanitize_input) { |val| val }
        expect_any_instance_of(PolyglotAPI).not_to receive(:call_go_service)
        expect_any_instance_of(PolyglotAPI).not_to receive(:call_python_service)

        post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(422)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to eq('Validation failed')
        expect(json_response['details']).to be_an(Array)
        expect(json_response['details'].first['field']).to eq('content')
      end
    end

    context 'when JSON is invalid, falls back to params' do
      it 'uses params and returns a valid response' do
        allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
        allow(RequestValidator).to receive(:sanitize_input) { |val| val }
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .and_return({ 'score' => 90.0, 'issues' => [] })

        post '/analyze?content=puts%201&path=test.rb', 'not-json', 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['summary']['language']).to eq('ruby')
        expect(json_response['summary']['review_score']).to eq(90.0)
      end
    end
  end

  describe 'POST /diff' do
    context 'when missing parameters' do
      it 'returns 400 if old_content or new_content is missing' do
        post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        json_response = JSON.parse(last_response.body)
        expect(json_response['error']).to eq('Missing old_content or new_content')
      end
    end

    context 'when parameters are valid' do
      it 'returns diff and new_code_review' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/diff', hash_including(old_content: 'a', new_content: 'b'), anything)
          .and_return({ 'diff' => '@@ -1 +1 @@' })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'b'), anything)
          .and_return({ 'score' => 88.0, 'issues' => [] })

        post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        json_response = JSON.parse(last_response.body)
        expect(json_response['diff']).to eq({ 'diff' => '@@ -1 +1 @@' })
        expect(json_response['new_code_review']).to include('score' => 88.0)
      end
    end
  end

  describe 'POST /metrics' do
    context 'when missing content' do
      it 'returns 400' do
        post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        expect(JSON.parse(last_response.body)['error']).to eq('Missing content')
      end
    end

    context 'when content is provided' do
      it 'returns metrics, review, and overall_quality computed' do
        metrics = { 'complexity' => 3 }
        review = { 'score' => 80, 'issues' => %w[i1 i2] }
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/metrics', hash_including(content: 'x'), anything)
          .and_return(metrics)
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'x'), anything)
          .and_return(review)

        post '/metrics', { content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['metrics']).to eq(metrics)
        expect(body['review']).to eq(review)
        expect(body['overall_quality']).to eq(0)
      end
    end
  end

  describe 'POST /dashboard' do
    context 'when files param is missing' do
      it 'returns 400' do
        post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(400)
        expect(JSON.parse(last_response.body)['error']).to eq('Missing files array')
      end
    end

    context 'when files are provided' do
      it 'returns statistics and summary with calculated health score' do
        fixed_time = Time.utc(2024, 1, 1, 12, 0, 0)
        allow(Time).to receive(:now).and_return(fixed_time)

        file_stats = { 'total_files' => 2, 'total_lines' => 100, 'languages' => { 'ruby' => 1, 'python' => 1 } }
        review_stats = { 'average_score' => 90.0, 'total_issues' => 3, 'average_complexity' => 0.1 }

        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/statistics', hash_including(files: array_including('a.rb', 'b.py')), anything)
          .and_return(file_stats)
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/statistics', hash_including(files: array_including('a.rb', 'b.py')), anything)
          .and_return(review_stats)

        post '/dashboard', { files: ['a.rb', 'b.py'] }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['timestamp']).to eq(fixed_time.iso8601)
        expect(body['file_statistics']).to eq(file_stats)
        expect(body['review_statistics']).to eq(review_stats)
        expect(body['summary']['total_files']).to eq(2)
        expect(body['summary']['total_lines']).to eq(100)
        expect(body['summary']['languages']).to eq(file_stats['languages'])
        expect(body['summary']['average_quality_score']).to eq(90.0)
        expect(body['summary']['total_issues']).to eq(3)
        expect(body['summary']['health_score']).to eq(84.0)
      end

      it 'returns health score 0.0 when stats contain errors' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .and_return({ 'error' => 'oops' })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .and_return({ 'average_score' => 90.0, 'total_issues' => 0, 'average_complexity' => 0.0 })

        post '/dashboard', { files: ['a'] }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['summary']['health_score']).to eq(0.0)
      end
    end
  end

  describe 'GET /traces' do
    it 'returns all traces with count' do
      traces = [{ id: 1 }, { id: 2 }]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_traces']).to eq(2)
      expect(body['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    context 'when no traces found' do
      it 'returns 404 with error' do
        allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return([])

        get '/traces/abc'
        expect(last_response.status).to eq(404)
        expect(JSON.parse(last_response.body)['error']).to eq('No traces found for correlation ID')
      end
    end

    context 'when traces exist' do
      it 'returns trace details' do
        traces = [{ step: 'a' }, { step: 'b' }]
        allow(CorrelationIdMiddleware).to receive(:get_traces).with('xyz').and_return(traces)

        get '/traces/xyz'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['correlation_id']).to eq('xyz')
        expect(body['trace_count']).to eq(2)
        expect(body['traces']).to eq(traces)
      end
    end
  end

  describe 'GET /validation/errors' do
    it 'returns collected validation errors' do
      errors = [{ field: 'content', message: 'missing' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_errors']).to eq(1)
      expect(body['errors']).to eq(errors)
    end
  end

  describe 'DELETE /validation/errors' do
    it 'clears validation errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)
      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      expect(JSON.parse(last_response.body)['message']).to eq('Validation errors cleared')
    end
  end

  describe 'private helper methods' do
    let(:instance) do
      app.new!
    end

    describe '#detect_language' do
      it 'detects language by extension' do
        expect(instance.send(:detect_language, 'file.go')).to eq('go')
        expect(instance.send(:detect_language, 'script.PY')).to eq('python')
        expect(instance.send(:detect_language, 'test.rb')).to eq('ruby')
        expect(instance.send(:detect_language, 'unknown.ext')).to eq('unknown')
        expect(instance.send(:detect_language, 'README')).to eq('unknown')
      end
    end

    describe '#check_service_health' do
      it 'returns healthy when service responds 200' do
        allow(HTTParty).to receive(:get).and_return(double(code: 200))
        result = instance.send(:check_service_health, 'http://svc')
        expect(result).to eq({ status: 'healthy' })
      end

      it 'returns unreachable with error on exception' do
        allow(HTTParty).to receive(:get).and_raise(StandardError.new('boom'))
        result = instance.send(:check_service_health, 'http://svc')
        expect(result[:status]).to eq('unreachable')
        expect(result[:error]).to include('boom')
      end
    end

    describe '#call_go_service' do
      it 'posts to go service and parses JSON response' do
        response = double(body: '{"ok":true}')
        expect(HTTParty).to receive(:post).with(
          "#{app.settings.go_service_url}/parse",
          hash_including(
            body: { input: 1 }.to_json,
            headers: include('Content-Type' => 'application/json',
                             CorrelationIdMiddleware::CORRELATION_ID_HEADER => 'cid'),
            timeout: 5
          )
        ).and_return(response)

        result = instance.send(:call_go_service, '/parse', { input: 1 }, 'cid')
        expect(result).to eq({ 'ok' => true })
      end

      it 'returns error hash when request fails' do
        allow(HTTParty).to receive(:post).and_raise(StandardError.new('failed'))
        result = instance.send(:call_go_service, '/parse', { a: 1 }, 'cid')
        expect(result[:error]).to include('failed')
      end
    end

    describe '#call_python_service' do
      it 'posts to python service and parses JSON response' do
        response = double(body: '{"status":"ok"}')
        expect(HTTParty).to receive(:post).with(
          "#{app.settings.python_service_url}/review",
          hash_including(
            body: { content: 'x' }.to_json,
            headers: include('Content-Type' => 'application/json',
                             CorrelationIdMiddleware::CORRELATION_ID_HEADER => 'pcid'),
            timeout: 5
          )
        ).and_return(response)

        result = instance.send(:call_python_service, '/review', { content: 'x' }, 'pcid')
        expect(result).to eq({ 'status' => 'ok' })
      end

      it 'returns error hash when request fails' do
        allow(HTTParty).to receive(:post).and_raise(StandardError.new('network error'))
        result = instance.send(:call_python_service, '/review', { y: 2 }, 'pcid')
        expect(result[:error]).to include('network error')
      end
    end

    describe '#calculate_quality_score' do
      it 'returns 0.0 when inputs are invalid or contain errors' do
        expect(instance.send(:calculate_quality_score, nil, {})).to eq(0.0)
        expect(instance.send(:calculate_quality_score, {}, nil)).to eq(0.0)
        expect(instance.send(:calculate_quality_score, { 'error' => 'x' }, { 'score' => 50 })).to eq(0.0)
        expect(instance.send(:calculate_quality_score, { 'complexity' => 1 }, { 'error' => 'x' })).to eq(0.0)
      end

      it 'calculates and clamps score correctly' do
        # Positive score
        metrics = { 'complexity' => 1 }
        review = { 'score' => 90, 'issues' => ['a'] }
        # base = 0.9, penalty = 0.1 + 0.5 = 0.6 => final = 0.3 => 30.0
        expect(instance.send(:calculate_quality_score, metrics, review)).to eq(30.0)

        # Clamp to 0
        metrics2 = { 'complexity' => 10 }
        review2 = { 'score' => 50, 'issues' => %w[a b c] }
        expect(instance.send(:calculate_quality_score, metrics2, review2)).to eq(0)

        # Clamp to 100
        metrics3 = { 'complexity' => 0 }
        review3 = { 'score' => 105, 'issues' => [] }
        expect(instance.send(:calculate_quality_score, metrics3, review3)).to eq(100)
      end
    end

    describe '#calculate_dashboard_health_score' do
      it 'returns 0.0 when inputs invalid or have errors' do
        expect(instance.send(:calculate_dashboard_health_score, nil, {})).to eq(0.0)
        expect(instance.send(:calculate_dashboard_health_score, {}, nil)).to eq(0.0)
        expect(instance.send(:calculate_dashboard_health_score, { 'error' => 'x' },
                             { 'average_score' => 80 })).to eq(0.0)
        expect(instance.send(:calculate_dashboard_health_score, { 'total_files' => 1 }, { 'error' => 'y' })).to eq(0.0)
      end

      it 'computes health score with penalties and clamps' do
        file_stats = { 'total_files' => 4 }
        review_stats = { 'average_score' => 95.0,
                         'total_issues' => 4, 'average_complexity' => 0.5 }
        # issue_penalty = (4/4)*2 = 2
        # complexity_penalty = 0.5 * 30 = 15
        # health = 95 - 2 - 15 = 78.0
        expect(instance.send(:calculate_dashboard_health_score,
                             file_stats, review_stats)).to eq(78.0)

        # Clamp to 0
        review_stats2 = { 'average_score' => 1.0,
                          'total_issues' => 100, 'average_complexity' => 2.0 }
        expect(instance.send(:calculate_dashboard_health_score,
                             file_stats, review_stats2)).to eq(0.0)

        # Clamp to 100
        review_stats3 = { 'average_score' => 150.0,
                          'total_issues' => 0, 'average_complexity' => 0.0 }
        expect(instance.send(:calculate_dashboard_health_score,
                             file_stats, review_stats3)).to eq(100.0)
      end
    end
  end
end
