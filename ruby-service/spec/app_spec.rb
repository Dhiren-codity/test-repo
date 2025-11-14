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
    it 'returns statuses for ruby, go, and python services' do
      allow(HTTParty).to receive(:get).with('http://localhost:8080/health', timeout: 2).and_return(double(code: 200))
      allow(HTTParty).to receive(:get).with('http://localhost:8081/health',
                                            timeout: 2).and_raise(StandardError.new('timeout'))

      get '/status'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['services']['ruby']['status']).to eq('healthy')
      expect(json['services']['go']['status']).to eq('healthy')
      expect(json['services']['python']['status']).to eq('unreachable')
      expect(json['services']['python']['error']).to match(/timeout/)
    end
  end

  describe 'POST /analyze validation and correlation' do
    it 'returns 422 with validation errors when invalid' do
      fake_error = double(to_hash: { field: 'content', message: 'missing' })
      allow(RequestValidator).to receive(:validate_analyze_request).and_return([fake_error])

      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Validation failed')
      expect(json['details']).to eq([{ 'field' => 'content', 'message' => 'missing' }])
    end

    it 'passes correlation id to downstream services and detects language from path' do
      cid_header = CorrelationIdMiddleware::CORRELATION_ID_HEADER
      header cid_header, 'abc-123'

      allow(RequestValidator).to receive(:validate_analyze_request).and_return([])
      allow(RequestValidator).to receive(:sanitize_input) do |val|
        val
      end

      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including({ content: 'puts 1', path: 'test.rb' }), 'abc-123')
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including({ content: 'puts 1', language: 'ruby' }), 'abc-123')
        .and_return({ 'score' => 90.0, 'issues' => [] })

      post '/analyze', { content: 'puts 1', path: 'test.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['correlation_id']).to eq('abc-123')
      expect(json['summary']['language']).to eq('ruby')
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when missing old_content or new_content' do
      post '/diff', { old_content: 'a' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new code review on success' do
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including({ old_content: 'a', new_content: 'b' }), nil)
        .and_return({ 'changes' => 1 })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including({ content: 'b' }), nil)
        .and_return({ 'score' => 70.0 })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['diff']).to eq({ 'changes' => 1 })
      expect(json['new_code_review']).to eq({ 'score' => 70.0 })
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing content')
    end

    it 'returns metrics, review, and overall_quality based on calculation' do
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including({ content: 'code' }), nil)
        .and_return({ 'complexity' => 2 })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including({ content: 'code' }), nil)
        .and_return({ 'score' => 80.0, 'issues' => [{}] })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['metrics']).to eq({ 'complexity' => 2 })
      expect(json['review']).to eq({ 'score' => 80.0, 'issues' => [{}] })
      expect(json['overall_quality']).to eq(10.0)
    end

    it 'returns overall_quality 0.0 when services report errors' do
      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'error' => 'fail' })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'error' => 'fail2' })

      post '/metrics', { content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['overall_quality']).to eq(0.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('Missing files array')
    end

    it 'returns summary and statistics with computed health score' do
      allow(Time).to receive(:now).and_return(Time.at(1_600_000_000))

      files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }, { 'path' => 'b.py', 'content' => 'print(1)' }]

      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including({ files: files }), nil)
        .and_return({ 'total_files' => 2, 'total_lines' => 100, 'languages' => { 'ruby' => 1, 'python' => 1 } })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including({ files: files }), nil)
        .and_return({ 'average_score' => 75.0, 'total_issues' => 3, 'average_complexity' => 0.1 })

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['timestamp']).to eq('2020-09-13T12:26:40Z')
      expect(json['summary']['total_files']).to eq(2)
      expect(json['summary']['total_lines']).to eq(100)
      expect(json['summary']['languages']).to eq({ 'ruby' => 1, 'python' => 1 })
      expect(json['summary']['average_quality_score']).to eq(75.0)
      expect(json['summary']['total_issues']).to eq(3)
      expect(json['summary']['health_score']).to eq(69.0)
    end
  end

  describe 'GET /traces' do
    it 'returns all traces and count' do
      traces = [{ 'id' => '1' }, { 'id' => '2' }]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['total_traces']).to eq(2)
      expect(json['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns 404 when no traces found' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return([])

      get '/traces/abc'
      expect(last_response.status).to eq(404)
      json = JSON.parse(last_response.body)
      expect(json['error']).to eq('No traces found for correlation ID')
    end

    it 'returns traces for the given correlation id' do
      trace_list = [{ 'step' => 'start' }, { 'step' => 'end' }]
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('xyz').and_return(trace_list)

      get '/traces/xyz'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['correlation_id']).to eq('xyz')
      expect(json['trace_count']).to eq(2)
      expect(json['traces']).to eq(trace_list)
    end
  end

  describe 'validation errors endpoints' do
    it 'GET /validation/errors returns stored errors' do
      errs = [{ 'field' => 'content', 'message' => 'missing' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errs)

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['total_errors']).to eq(1)
      expect(json['errors']).to eq(errs)
    end

    it 'DELETE /validation/errors clears errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)

      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      json = JSON.parse(last_response.body)
      expect(json['message']).to eq('Validation errors cleared')
    end
  end
end
