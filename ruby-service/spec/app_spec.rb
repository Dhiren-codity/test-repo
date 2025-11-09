# frozen_string_literal: true

require 'rails_helper'
require 'json'
require 'time'

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

    it 'returns 400 when content is missing' do
      post '/analyze', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end

    it 'falls back to params on invalid JSON and detects language for python review' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'language' => 'ruby', 'lines' => ['puts 1'] })
      expect_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', hash_including(language: 'ruby', content: 'puts 1'))
        .and_return({ 'score' => 90.0, 'issues' => [] })

      post '/analyze?content=puts%201&path=script.rb', 'not-json', 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['summary']).to include('review_score' => 90.0)
    end
  end

  describe 'GET /status' do
    it 'reports healthy for all services when dependencies return 200' do
      allow(HTTParty).to receive(:get).and_return(double(code: 200))

      get '/status'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      services = json_response['services']
      expect(services['ruby']['status']).to eq('healthy')
      expect(services['go']['status']).to eq('healthy')
      expect(services['python']['status']).to eq('healthy')
    end

    it 'reports unhealthy when a dependency returns non-200' do
      allow(HTTParty).to receive(:get).and_return(double(code: 200), double(code: 500))

      get '/status'
      expect(last_response.status).to eq(200)
      services = JSON.parse(last_response.body)['services']
      expect(services['go']['status']).to eq('healthy')
      expect(services['python']['status']).to eq('unhealthy')
    end

    it 'reports unreachable when a dependency raises an error' do
      allow(HTTParty).to receive(:get).and_raise(StandardError.new('boom'))

      get '/status'
      expect(last_response.status).to eq(200)
      services = JSON.parse(last_response.body)['services']
      expect(services['go']['status']).to eq('unreachable')
      expect(services['go']['error']).to match(/boom/)
      expect(services['python']['status']).to eq('unreachable')
      expect(services['python']['error']).to match(/boom/)
    end
  end

  describe 'POST /diff' do
    it 'returns diff and new_code_review for valid request' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/diff', anything).and_return({ 'changed_lines' => 3 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', anything).and_return({ 'score' => 72.5, 'issues' => [] })

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']).to eq({ 'changed_lines' => 3 })
      expect(json_response['new_code_review']).to include('score' => 72.5)
    end

    it 'returns 400 when old_content or new_content is missing' do
      post '/diff', { old_content: 'a' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing old_content or new_content')
    end

    it 'handles python review service failure gracefully' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .and_return({ 'changed_lines' => 1 })

      allow(HTTParty).to receive(:post).and_call_original
      allow(HTTParty).to receive(:post)
        .with('http://localhost:8081/review', any_args)
        .and_raise(StandardError.new('py down'))

      post '/diff', { old_content: 'a', new_content: 'b' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['diff']).to eq({ 'changed_lines' => 1 })
      expect(json_response['new_code_review']).to include('error' => match(/py down/))
    end
  end

  describe 'POST /metrics' do
    it 'computes overall_quality using metrics and review (clamped to 0)' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', anything).and_return({ 'complexity' => 5 })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', anything).and_return({ 'score' => 80, 'issues' => [1, 2] })

      post '/metrics', { content: 'code' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['overall_quality']).to eq(0.0)
    end

    it 'returns 400 when content is missing' do
      post '/metrics', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing content')
    end

    it 'returns overall_quality 0.0 when metrics has error' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/metrics', anything).and_return({ 'error' => 'timeout' })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/review', anything).and_return({ 'score' => 95, 'issues' => [] })

      post '/metrics', { content: 'x' }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['overall_quality']).to eq(0.0)
    end
  end

  describe 'POST /dashboard' do
    it 'returns 400 when files array is missing or empty' do
      post '/dashboard', {}.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(400)
      json_response = JSON.parse(last_response.body)
      expect(json_response['error']).to eq('Missing files array')
    end

    it 'returns dashboard stats and computed health_score' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', anything).and_return({
                                                    'total_files' => 2,
                                                    'total_lines' => 100,
                                                    'languages' => { 'ruby' => 1, 'python' => 1 }
                                                  })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', anything).and_return({
                                                    'average_score' => 90.0,
                                                    'total_issues' => 1,
                                                    'average_complexity' => 0.1
                                                  })

      files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }, { 'path' => 'b.py', 'content' => 'print(1)' }]
      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect { Time.iso8601(json_response['timestamp']) }.not_to raise_error
      expect(json_response['summary']).to include(
        'total_files' => 2,
        'total_lines' => 100,
        'languages' => { 'ruby' => 1, 'python' => 1 },
        'average_quality_score' => 90.0,
        'total_issues' => 1
      )
      # health_score = 90 - ((1/2)*2) - (0.1*30) = 86.0
      expect(json_response['summary']['health_score']).to eq(86.0)
    end

    it 'clamps health_score to 0 when penalties exceed score' do
      allow_any_instance_of(PolyglotAPI).to receive(:call_go_service)
        .with('/statistics', anything).and_return({
                                                    'total_files' => 1,
                                                    'total_lines' => 10,
                                                    'languages' => { 'ruby' => 1 }
                                                  })
      allow_any_instance_of(PolyglotAPI).to receive(:call_python_service)
        .with('/statistics', anything).and_return({
                                                    'average_score' => 10.0,
                                                    'total_issues' => 100,
                                                    'average_complexity' => 10.0
                                                  })

      files = [{ 'path' => 'a.rb', 'content' => 'puts 1' }]
      post '/dashboard', { files: files }.to_json, 'CONTENT_TYPE' => 'application/json'
      expect(last_response.status).to eq(200)
      json_response = JSON.parse(last_response.body)
      expect(json_response['summary']['health_score']).to eq(0.0)
    end
  end
end
