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
    context 'when downstream services are healthy' do
      it 'reports healthy for go and python' do
        allow(HTTParty).to receive(:get).with('http://localhost:8080/health', timeout: 2).and_return(double(code: 200))
        allow(HTTParty).to receive(:get).with('http://localhost:8081/health', timeout: 2).and_return(double(code: 200))

        get '/status'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['services']['ruby']['status']).to eq('healthy')
        expect(body['services']['go']['status']).to eq('healthy')
        expect(body['services']['python']['status']).to eq('healthy')
      end
    end

    context 'when a service is unhealthy' do
      it 'reports unhealthy based on HTTP status code' do
        allow(HTTParty).to receive(:get).with('http://localhost:8080/health', timeout: 2).and_return(double(code: 500))
        allow(HTTParty).to receive(:get).with('http://localhost:8081/health', timeout: 2).and_return(double(code: 200))

        get '/status'
        body = JSON.parse(last_response.body)
        expect(body['services']['go']['status']).to eq('unhealthy')
        expect(body['services']['python']['status']).to eq('healthy')
      end
    end

    context 'when a service is unreachable' do
      it 'reports unreachable with error message' do
        allow(HTTParty).to receive(:get).with('http://localhost:8080/health', timeout: 2).and_return(double(code: 200))
        allow(HTTParty).to receive(:get).with('http://localhost:8081/health',
                                              timeout: 2).and_raise(Timeout::Error.new('execution expired'))

        get '/status'
        body = JSON.parse(last_response.body)
        expect(body['services']['go']['status']).to eq('healthy')
        expect(body['services']['python']['status']).to eq('unreachable')
        expect(body['services']['python']).to have_key('error')
      end
    end
  end

  describe 'POST /analyze validation' do
    it 'returns 422 when validation fails' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([
                                                                                 double(to_hash: { field: 'content',
                                                                                                   message: 'is required' })
                                                                               ])

      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Validation failed')
      expect(body['details']).to be_an(Array)
      expect(body['details'].first['field']).to eq('content')
    end

    it 'propagates correlation id and uses unknown language when path is missing' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) do |arg|
        arg
      end

      header_name = CorrelationIdMiddleware::CORRELATION_ID_HEADER
      header header_name, 'cid-123'

      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'code', path: 'unknown'), 'cid-123')
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code', language: 'unknown'), 'cid-123')
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/analyze', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['correlation_id']).to eq('cid-123')
    end

    it 'detects language from file extension' do
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) do |arg|
        arg
      end

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ['line'] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'ruby', content: 'puts 1'), kind_of(String))
        .and_return({ 'score' => 80, 'issues' => [] })

      header CorrelationIdMiddleware::CORRELATION_ID_HEADER, 'corr-1'
      post '/analyze', { content: 'puts 1', path: 'test.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when old_content or new_content is missing' do
      post '/diff', { old_content: 'a' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new code review on success' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: 'a', new_content: 'b'))
        .and_return({ 'diff' => ['+b', '-a'] })

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'b'))
        .and_return({ 'score' => 70, 'issues' => ['issue'] })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['diff']).to eq({ 'diff' => ['+b', '-a'] })
      expect(body['new_code_review']).to eq({ 'score' => 70, 'issues' => ['issue'] })
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing content')
    end

    it 'computes overall_quality from metrics and review' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'code'))
        .and_return({ 'complexity' => 1 })

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code'))
        .and_return({ 'score' => 90, 'issues' => ['a'] })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['overall_quality']).to eq(30.0)
      expect(body['metrics']).to eq({ 'complexity' => 1 })
      expect(body['review']).to eq({ 'score' => 90, 'issues' => ['a'] })
    end

    it 'falls back to params when JSON is invalid' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'complexity' => 0 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 100, 'issues' => [] })

      post '/metrics?content=ok', 'invalid-json', 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['metrics']).to eq({ 'complexity' => 0 })
      expect(body['review']).to eq({ 'score' => 100, 'issues' => [] })
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing files array')
    end

    it 'returns statistics, review stats, and summary with health score' do
      file_stats = {
        'total_files' => 5,
        'total_lines' => 100,
        'languages' => { 'ruby' => 3 }
      }
      review_stats = {
        'average_score' => 80.0,
        'total_issues' => 10,
        'average_complexity' => 0.5
      }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: ['a.rb', 'b.rb']))
        .and_return(file_stats)

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: ['a.rb', 'b.rb']))
        .and_return(review_stats)

      post '/dashboard', { files: ['a.rb', 'b.rb'] }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['file_statistics']).to eq(file_stats)
      expect(body['review_statistics']).to eq(review_stats)
      expect(body['summary']['total_files']).to eq(5)
      expect(body['summary']['average_quality_score']).to eq(80.0)
      expect(body['summary']['health_score']).to eq(61.0)
      expect(body['timestamp']).to be_a(String)
    end
  end

  describe 'GET /traces' do
    it 'returns all traces with count' do
      traces = [
        { 'id' => 't1', 'path' => '/analyze' },
        { 'id' => 't2', 'path' => '/metrics' }
      ]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_traces']).to eq(2)
      expect(body['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns 404 when no traces found' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return([])

      get '/traces/abc'
      expect(last_response.status).to eq(404)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('No traces found for correlation ID')
    end

    it 'returns traces for a given correlation id' do
      traces = [{ 'event' => 'start' }, { 'event' => 'end' }]
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('xyz').and_return(traces)

      get '/traces/xyz'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['correlation_id']).to eq('xyz')
      expect(body['trace_count']).to eq(2)
      expect(body['traces']).to eq(traces)
    end
  end

  describe 'validation errors registry endpoints' do
    it 'returns validation errors list' do
      errors = [{ 'field' => 'content', 'message' => 'missing' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errors)

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_errors']).to eq(1)
      expect(body['errors']).to eq(errors)
    end

    it 'clears validation errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)

      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['message']).to eq('Validation errors cleared')
    end
  end
end
