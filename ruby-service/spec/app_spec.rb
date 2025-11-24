# frozen_string_literal: true

require_relative 'spec_helper'
require_relative '../app/app'

RSpec.describe PolyglotAPI do
  include Rack::Test::Methods

  def app
    PolyglotAPI
  end

  let(:go_url) do
    PolyglotAPI.settings.go_service_url
  end

  let(:python_url) do
    PolyglotAPI.settings.python_service_url
  end

  let(:cache_url) do
    PolyglotAPI.settings.cache_service_url
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
    it 'reports all services healthy' do
      allow(HTTParty).to receive(:get)
        .with("#{go_url}/health", timeout: 2)
        .and_return(double(code: 200))
      allow(HTTParty).to receive(:get)
        .with("#{python_url}/health", timeout: 2)
        .and_return(double(code: 200))
      allow(HTTParty).to receive(:get)
        .with("#{cache_url}/health", timeout: 2)
        .and_return(double(code: 200))

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['ruby']['status']).to eq('healthy')
      expect(json_response['services']['go']['status']).to eq('healthy')
      expect(json_response['services']['python']['status']).to eq('healthy')
      expect(json_response['services']['cache']['status']).to eq('healthy')
    end

    it 'handles unhealthy and unreachable services' do
      allow(HTTParty).to receive(:get)
        .with("#{go_url}/health", timeout: 2)
        .and_return(double(code: 200))
      allow(HTTParty).to receive(:get)
        .with("#{python_url}/health", timeout: 2)
        .and_return(double(code: 500))
      allow(HTTParty).to receive(:get)
        .with("#{cache_url}/health", timeout: 2)
        .and_raise(StandardError.new('connection refused'))

      get '/status'
      json_response = JSON.parse(last_response.body)
      expect(json_response['services']['go']['status']).to eq('healthy')
      expect(json_response['services']['python']['status']).to eq('unhealthy')
      expect(json_response['services']['cache']['status']).to eq('unreachable')
      expect(json_response['services']['cache']['error']).to include('connection refused')
    end
  end

  describe 'GET /cache/stats' do
    it 'returns cache stats from cache service' do
      allow(HTTParty).to receive(:get)
        .with("#{cache_url}/cache/stats", timeout: 3)
        .and_return(double(body: { hits: 3, misses: 1 }.to_json))

      get '/cache/stats'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['hits']).to eq(3)
      expect(json_response['misses']).to eq(1)
    end

    it 'returns error when cache service fails' do
      allow(HTTParty).to receive(:get)
        .with("#{cache_url}/cache/stats", timeout: 3)
        .and_raise(StandardError.new('timeout'))

      get '/cache/stats'
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to include('timeout')
    end
  end

  describe 'POST /cache/invalidate' do
    it 'invalidates cache for a specific service and key with JSON body' do
      allow(HTTParty).to receive(:post)
        .with(
          "#{cache_url}/cache/invalidate",
          body: { service: 'go', key: 'abc' }.to_json,
          headers: { 'Content-Type' => 'application/json' },
          timeout: 3
        )
        .and_return(double(body: { status: 'ok' }.to_json))

      post '/cache/invalidate', { service: 'go', key: 'abc' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('ok')
    end

    it 'falls back to params when JSON parsing fails' do
      allow(HTTParty).to receive(:post)
        .with(
          "#{cache_url}/cache/invalidate",
          body: { service: 'python', key: 'k1' }.to_json,
          headers: { 'Content-Type' => 'application/json' },
          timeout: 3
        )
        .and_return(double(body: { status: 'ok' }.to_json))

      post '/cache/invalidate?service=python&key=k1', 'not-json', 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['status']).to eq('ok')
    end

    it 'returns 400 when service is missing' do
      post '/cache/invalidate', { key: 'abc' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing service parameter')
    end

    it 'returns error message when cache service fails' do
      allow(HTTParty).to receive(:post)
        .with(
          "#{cache_url}/cache/invalidate",
          body: { service: 'go', key: 'abc' }.to_json,
          headers: { 'Content-Type' => 'application/json' },
          timeout: 3
        )
        .and_raise(StandardError.new('service down'))

      post '/cache/invalidate', { service: 'go', key: 'abc' }.to_json, 'CONTENT_TYPE' => 'application/json'
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to include('service down')
    end
  end

  describe 'POST /cache/invalidate-all' do
    it 'clears caches across all services when all succeed' do
      allow(HTTParty).to receive(:post)
        .with("#{go_url}/cache/clear", timeout: 3)
        .and_return(double(body: 'ok'))
      allow(HTTParty).to receive(:post)
        .with("#{python_url}/cache/clear", timeout: 3)
        .and_return(double(body: 'ok'))
      allow(HTTParty).to receive(:post)
        .with("#{cache_url}/cache/invalidate-all", timeout: 3)
        .and_return(double(body: 'ok'))

      post '/cache/invalidate-all'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['message']).to eq('Cache invalidation completed')
      expect(json_response['cleared_services']).to include('go', 'python', 'cache')
    end

    it 'reports failures for services that cannot clear cache' do
      allow(HTTParty).to receive(:post)
        .with("#{go_url}/cache/clear", timeout: 3)
        .and_return(double(body: 'ok'))
      allow(HTTParty).to receive(:post)
        .with("#{python_url}/cache/clear", timeout: 3)
        .and_raise(StandardError.new('py down'))
      allow(HTTParty).to receive(:post)
        .with("#{cache_url}/cache/invalidate-all", timeout: 3)
        .and_return(double(body: 'ok'))

      post '/cache/invalidate-all'
      json_response = JSON.parse(last_response.body)
      expect(json_response['cleared_services']).to include('go', 'cache')
      expect(json_response['cleared_services'].any? { |s| s.include?('python (failed: py down)') }).to be true
    end
  end

  describe 'POST /analyze language detection' do
    it 'passes detected language to python service based on file extension' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ['def x; end'] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'ruby', content: 'def foo; end'))
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/analyze', { content: 'def foo; end', path: 'lib/test.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
    end

    it 'returns 400 when content is missing' do
      post '/analyze', { path: 'file.py' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end
  end

  describe 'POST /diff' do
    it 'returns diff and review for valid inputs' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'changes' => 2 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 75, 'issues' => [] })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']['changes']).to eq(2)
      expect(json_response['new_code_review']['score']).to eq(75)
    end

    it 'returns 400 when required fields are missing' do
      post '/diff', { old_content: 'a' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing old_content or new_content')
    end

    it 'handles go diff service failure gracefully' do
      allow(HTTParty).to receive(:post)
        .with("#{go_url}/diff", anything)
        .and_raise(StandardError.new('go down'))
      allow(HTTParty).to receive(:post)
        .with("#{python_url}/review", anything)
        .and_return(double(body: { score: 70, issues: [] }.to_json))

      post '/diff', { old_content: 'x', new_content: 'y' }.to_json, 'CONTENT_TYPE' => 'application/json'
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']['error']).to include('go down')
      expect(json_response['new_code_review']['score']).to eq(70)
    end
  end

  describe 'POST /metrics' do
    it 'returns metrics, review, and overall quality score' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'complexity' => 2 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 80, 'issues' => [{}] })

      post '/metrics', { content: 'print("hi")' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['metrics']['complexity']).to eq(2)
      expect(json_response['review']['score']).to eq(80)
      expect(json_response['overall_quality']).to eq(10.0)
    end

    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end

    it 'returns overall_quality 0.0 when services return errors' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'error' => 'timeout' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .and_return({ 'score' => 90, 'issues' => [] })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      json_response = JSON.parse(last_response.body)
      expect(json_response['overall_quality']).to eq(0.0)
    end
  end
end
