# frozen_string_literal: true

require 'spec_helper'
require 'json'
require 'time'
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
    it 'aggregates health statuses from services' do
      allow_any_instance_of(PolyglotAPI).to receive(:check_service_health)
        .and_return({ status: 'healthy' }, { status: 'unreachable', error: 'timeout' })

      get '/status'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['services']['ruby']['status']).to eq('healthy')
      expect(body['services']['go']['status']).to eq('healthy')
      expect(body['services']['python']['status']).to eq('unreachable')
      expect(body['services']['python']['error']).to eq('timeout')
    end
  end

  describe 'POST /analyze validations and tracing' do
    it 'returns 422 with validation errors when invalid' do
      allow(RequestValidator).to receive(:validate_analyze_request)
        .and_return([double(to_hash: { 'field' => 'content', 'message' => 'missing' })])

      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(422)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Validation failed')
      expect(body['details']).to be_an(Array)
      expect(body['details'].first['field']).to eq('content')
    end

    it 'propagates correlation id and detects language for python service' do
      cid = 'cid-123'
      header CorrelationIdMiddleware::CORRELATION_ID_HEADER, cid

      expect_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/parse', hash_including(content: 'code here', path: 'file.ts'), cid)
        .and_return({ 'language' => 'typescript', 'lines' => %w[a b] })

      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'code here', language: 'typescript'), cid)
        .and_return({ 'score' => 50, 'issues' => ['i1'] })

      post '/analyze', { content: 'code here', path: 'file.ts' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['correlation_id']).to eq(cid)
      expect(body['summary']['lines']).to eq(2)
      expect(body['summary']['issues_count']).to eq(1)
      expect(body['summary']['review_score']).to eq(50)
    end
  end

  describe 'POST /diff' do
    it 'returns 400 when old_content or new_content missing' do
      post '/diff', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('Missing old_content or new_content')
    end

    it 'returns diff and new code review when inputs provided' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', hash_including(old_content: 'a', new_content: 'b'))
        .and_return({ 'changes' => [] })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'b'))
        .and_return({ 'score' => 77.0, 'issues' => [] })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['diff']).to eq({ 'changes' => [] })
      expect(body['new_code_review']['score']).to eq(77.0)
    end
  end

  describe 'POST /metrics' do
    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      expect(JSON.parse(last_response.body)['error']).to eq('Missing content')
    end

    it 'returns metrics, review, and overall_quality' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', hash_including(content: 'x'))
        .and_return({ 'complexity' => 1 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(content: 'x'))
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/metrics', { content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['metrics']['complexity']).to eq(1)
      expect(body['review']['score']).to eq(90)
      expect(body['overall_quality']).to eq(80.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array missing' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      expect(JSON.parse(last_response.body)['error']).to eq('Missing files array')
    end

    it 'returns dashboard data with summary and health score' do
      fixed_time = Time.utc(2024, 1, 2, 3, 4, 5)
      allow(Time).to receive(:now).and_return(fixed_time)

      files = [{ 'path' => 'a.rb', 'content' => 'x' }, { 'path' => 'b.rb', 'content' => 'y' }]

      file_stats = {
        'total_files' => 2,
        'total_lines' => 100,
        'languages' => { 'ruby' => 2 }
      }
      review_stats = {
        'average_score' => 90.0,
        'total_issues' => 1,
        'average_complexity' => 0.1
      }

      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', hash_including(files: files))
        .and_return(file_stats)

      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', hash_including(files: files))
        .and_return(review_stats)

      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['timestamp']).to eq('2024-01-02T03:04:05Z')
      expect(body['file_statistics']).to eq(file_stats)
      expect(body['review_statistics']).to eq(review_stats)
      expect(body['summary']['total_files']).to eq(2)
      expect(body['summary']['total_lines']).to eq(100)
      expect(body['summary']['languages']).to eq({ 'ruby' => 2 })
      expect(body['summary']['average_quality_score']).to eq(90.0)
      expect(body['summary']['total_issues']).to eq(1)
      expect(body['summary']['health_score']).to eq(86.0)
    end
  end

  describe 'GET /traces' do
    it 'returns all traces with count' do
      traces = [{ 'id' => '1' }, { 'id' => '2' }]
      allow(CorrelationIdMiddleware).to receive(:all_traces).and_return(traces)

      get '/traces'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_traces']).to eq(2)
      expect(body['traces']).to eq(traces)
    end
  end

  describe 'GET /traces/:correlation_id' do
    it 'returns 404 when no traces' do
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('abc').and_return([])

      get '/traces/abc'
      expect(last_response.status).to eq(404)
      body = JSON.parse(last_response.body)
      expect(body['error']).to eq('No traces found for correlation ID')
    end

    it 'returns traces for the given correlation id' do
      traces = [{ 'step' => 1 }, { 'step' => 2 }]
      allow(CorrelationIdMiddleware).to receive(:get_traces).with('xyz').and_return(traces)

      get '/traces/xyz'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['correlation_id']).to eq('xyz')
      expect(body['trace_count']).to eq(2)
      expect(body['traces']).to eq(traces)
    end
  end

  describe 'validation errors endpoints' do
    it 'GET /validation/errors returns list and count' do
      errs = [{ 'field' => 'content', 'message' => 'missing' }]
      allow(RequestValidator).to receive(:get_validation_errors).and_return(errs)

      get '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['total_errors']).to eq(1)
      expect(body['errors']).to eq(errs)
    end

    it 'DELETE /validation/errors clears errors' do
      expect(RequestValidator).to receive(:clear_validation_errors)

      delete '/validation/errors'
      expect(last_response.status).to eq(200)
      body = JSON.parse(last_response.body)
      expect(body['message']).to eq('Validation errors cleared')
    end
  end
end
