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
    context 'when all services are healthy' do
      it 'returns healthy for go, python, and cache services' do
        allow(HTTParty).to receive(:get).with("#{app.settings.go_service_url}/health",
                                              timeout: 2).and_return(double(code: 200))
        allow(HTTParty).to receive(:get).with("#{app.settings.python_service_url}/health",
                                              timeout: 2).and_return(double(code: 200))
        allow(HTTParty).to receive(:get).with("#{app.settings.cache_service_url}/health",
                                              timeout: 2).and_return(double(code: 200))

        get '/status'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['services']['ruby']['status']).to eq('healthy')
        expect(body['services']['go']['status']).to eq('healthy')
        expect(body['services']['python']['status']).to eq('healthy')
        expect(body['services']['cache']['status']).to eq('healthy')
      end
    end

    context 'when a service is unreachable' do
      it 'returns unreachable status with error message' do
        allow(HTTParty).to receive(:get).with("#{app.settings.go_service_url}/health",
                                              timeout: 2).and_raise(StandardError.new('connection refused'))
        allow(HTTParty).to receive(:get).with("#{app.settings.python_service_url}/health",
                                              timeout: 2).and_return(double(code: 200))
        allow(HTTParty).to receive(:get).with("#{app.settings.cache_service_url}/health",
                                              timeout: 2).and_return(double(code: 200))

        get '/status'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['services']['go']['status']).to eq('unreachable')
        expect(body['services']['go']['error']).to include('connection refused')
      end
    end
  end

  describe 'GET /cache/stats' do
    context 'when cache service responds successfully' do
      it 'returns cache stats as JSON' do
        resp = double(body: { hits: 10, misses: 2 }.to_json)
        allow(HTTParty).to receive(:get).with("#{app.settings.cache_service_url}/cache/stats",
                                              timeout: 3).and_return(resp)

        get '/cache/stats'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['hits']).to eq(10)
        expect(body['misses']).to eq(2)
      end
    end

    context 'when cache service raises an error' do
      it 'returns an error json' do
        allow(HTTParty).to receive(:get).with("#{app.settings.cache_service_url}/cache/stats",
                                              timeout: 3).and_raise(Timeout::Error.new('execution expired'))

        get '/cache/stats'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['error']).to include('execution expired')
      end
    end
  end

  describe 'POST /cache/invalidate' do
    context 'when request is valid' do
      it 'forwards the request to cache service and returns its response' do
        response = double(body: { invalidated: true }.to_json)
        allow(HTTParty).to receive(:post)
          .with("#{app.settings.cache_service_url}/cache/invalidate", hash_including(timeout: 3))
          .and_return(response)

        post '/cache/invalidate', { service: 'go', key: 'file_123' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['invalidated']).to be(true)
      end
    end

    context 'when service parameter is missing' do
      it 'returns an error message' do
        post '/cache/invalidate', { key: 'file_123' }.to_json, 'CONTENT_TYPE' => 'application/json'
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing service parameter')
      end
    end

    context 'when cache service returns an error' do
      it 'returns an error json' do
        allow(HTTParty).to receive(:post)
          .with("#{app.settings.cache_service_url}/cache/invalidate", hash_including(timeout: 3))
          .and_raise(StandardError.new('boom'))

        post '/cache/invalidate', { service: 'python' }.to_json, 'CONTENT_TYPE' => 'application/json'
        body = JSON.parse(last_response.body)
        expect(body['error']).to include('boom')
      end
    end
  end

  describe 'POST /cache/invalidate-all' do
    context 'when all services clear cache successfully' do
      it 'lists all services as cleared' do
        allow(HTTParty).to receive(:post).with("#{app.settings.go_service_url}/cache/clear",
                                               timeout: 3).and_return(double)
        allow(HTTParty).to receive(:post).with("#{app.settings.python_service_url}/cache/clear",
                                               timeout: 3).and_return(double)
        allow(HTTParty).to receive(:post).with("#{app.settings.cache_service_url}/cache/invalidate-all",
                                               timeout: 3).and_return(double)

        post '/cache/invalidate-all'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['message']).to eq('Cache invalidation completed')
        expect(body['cleared_services']).to eq(%w[go python cache])
      end
    end

    context 'when some services fail' do
      it 'includes failure messages for those services' do
        allow(HTTParty).to receive(:post).with("#{app.settings.go_service_url}/cache/clear",
                                               timeout: 3).and_raise(StandardError.new('go down'))
        allow(HTTParty).to receive(:post).with("#{app.settings.python_service_url}/cache/clear",
                                               timeout: 3).and_return(double)
        allow(HTTParty).to receive(:post).with("#{app.settings.cache_service_url}/cache/invalidate-all",
                                               timeout: 3).and_raise(StandardError.new('cache error'))

        post '/cache/invalidate-all'
        body = JSON.parse(last_response.body)
        expect(body['cleared_services']).to eq(['go (failed: go down)', 'python', 'cache (failed: cache error)'])
      end
    end
  end

  describe 'POST /analyze additional cases' do
    context 'when content is missing' do
      it 'returns an error message' do
        post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing content')
      end
    end

    context 'when detecting language from path' do
      it 'passes detected language to python review service' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .and_return({ 'language' => 'ruby', 'lines' => ['def x'] })
        expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(language: 'ruby'))
          .and_return({ 'score' => 70, 'issues' => [] })

        post '/analyze', { content: 'def x; end', path: 'file.rb' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['summary']['language']).to eq('ruby')
      end
    end
  end

  describe 'POST /diff' do
    context 'when required content is missing' do
      it 'returns an error message' do
        post '/diff', { old_content: 'a' }.to_json, 'CONTENT_TYPE' => 'application/json'
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing old_content or new_content')
      end
    end

    context 'when both contents are provided' do
      it 'returns diff and new code review' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/diff', hash_including(old_content: 'a', new_content: 'b'))
          .and_return({ 'changes' => ['+b', '-a'] })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'b'))
          .and_return({ 'score' => 95, 'issues' => [] })

        post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['diff']['changes']).to eq(['+b', '-a'])
        expect(body['new_code_review']['score']).to eq(95)
      end
    end
  end

  describe 'POST /metrics' do
    context 'when content is missing' do
      it 'returns an error message' do
        post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
        body = JSON.parse(last_response.body)
        expect(body['error']).to eq('Missing content')
      end
    end

    context 'when services return data for quality computation' do
      it 'calculates overall quality score based on metrics and review' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/metrics', hash_including(content: 'x'))
          .and_return({ 'complexity' => 3 })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'x'))
          .and_return({ 'score' => 90, 'issues' => ['warn'] })

        post '/metrics', { content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['overall_quality']).to eq(10.0)
        expect(body['metrics']['complexity']).to eq(3)
        expect(body['review']['score']).to eq(90)
      end
    end

    context 'when one of the services reports an error' do
      it 'returns overall quality score of 0.0' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/metrics', hash_including(content: 'y'))
          .and_return({ 'error' => 'timeout' })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'y'))
          .and_return({ 'score' => 80, 'issues' => [] })

        post '/metrics', { content: 'y' }.to_json, 'CONTENT_TYPE' => 'application/json'
        body = JSON.parse(last_response.body)
        expect(body['overall_quality']).to eq(0.0)
      end
    end

    context 'when JSON body is invalid but params are provided' do
      it 'falls back to params and processes the request' do
        allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
          .with('/metrics', hash_including(content: 'param-content'))
          .and_return({ 'complexity' => 1 })
        allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
          .with('/review', hash_including(content: 'param-content'))
          .and_return({ 'score' => 100, 'issues' => [] })

        post '/metrics?content=param-content', 'invalid{', 'CONTENT_TYPE' => 'application/json'
        expect(last_response.status).to eq(200)
        body = JSON.parse(last_response.body)
        expect(body['metrics']['complexity']).to eq(1)
        expect(body['review']['score']).to eq(100)
      end
    end
  end
end
